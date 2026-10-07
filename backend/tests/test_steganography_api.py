from __future__ import annotations

import io
import json

import numpy as np
import pytest
from PIL import Image
from skimage import data as skdata
from sqlalchemy import select

from app.db.models import AuditLog, StegoOperation
from app.db.session import SessionLocal
from tests.conftest import auth_header, make_user


def _png(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def cover_png() -> bytes:
    return _png(skdata.astronaut())


def _embed(client, token, cover_png, algorithm="lsb", **form):
    data = {"algorithm": algorithm, "payload_type": "text", "message": "The vault code is 7-4-1-9", "key_mode": "passphrase", "passphrase": "orbital-lantern-58"}
    data.update(form)
    return client.post(
        "/api/steganography/embed",
        headers=auth_header(token),
        files={"image": ("cover.png", cover_png, "image/png")},
        data=data,
    )


@pytest.mark.parametrize("algorithm", ["lsb", "dct", "dwt"])
def test_embed_download_extract_decrypt(client, cover_png, algorithm):
    token = make_user(client, f"stego-{algorithm}@example.com")
    response = _embed(client, token, cover_png, algorithm)
    assert response.status_code == 200, response.text
    body = response.json()
    result = body["result"]
    assert result["encryption"]["cipher"] == "AES-256-GCM"
    assert result["encryption"]["kdf"] == "argon2id"
    assert result["quality"]["psnr"] > 40
    assert result["generated_key"] is None
    stages = [event["stage"] for event in body["trace"]]
    assert {"validate", "crypto", "embed", "metrics", "store"} <= set(stages)

    stego = client.get(f"/api/artifacts/{result['artifacts']['stego']}?download=true", headers=auth_header(token))
    assert stego.status_code == 200 and stego.headers["content-type"] == "image/png"

    extracted = client.post(
        "/api/steganography/extract",
        headers=auth_header(token),
        files={"image": ("stego.png", stego.content, "image/png")},
        data={"algorithm": "auto", "secret": "orbital-lantern-58"},
    ).json()["result"]
    assert extracted["detected_algorithm"] == algorithm
    assert extracted["integrity"]["status"] == "verified"
    assert extracted["decryption"]["status"] == "success"
    assert extracted["payload"]["text"] == "The vault code is 7-4-1-9"

    with SessionLocal() as db:
        ops = db.scalars(select(StegoOperation).where(StegoOperation.stego_hash == result["stego"]["sha256"])).all()
        assert {op.operation for op in ops} == {"embed", "extract"}
        # The secret message itself is never persisted.
        for op in ops:
            assert "vault" not in json.dumps(op.artifacts)


def test_wrong_key_fails_safely_and_is_audited(client, cover_png):
    token = make_user(client, "wrongkey@example.com")
    result = _embed(client, token, cover_png, "dct").json()["result"]
    stego = client.get(f"/api/artifacts/{result['artifacts']['stego']}", headers=auth_header(token)).content
    extracted = client.post(
        "/api/steganography/extract",
        headers=auth_header(token),
        files={"image": ("stego.png", stego, "image/png")},
        data={"secret": "definitely-not-it"},
    ).json()["result"]
    assert extracted["integrity"]["status"] == "verified"
    assert extracted["decryption"]["status"] == "failed"
    assert extracted["payload"] is None
    with SessionLocal() as db:
        actions = {row.action for row in db.scalars(select(AuditLog).where(AuditLog.user_email == "wrongkey@example.com"))}
        assert "DECRYPTION_FAILURE" in actions
        for row in db.scalars(select(AuditLog).where(AuditLog.user_email == "wrongkey@example.com")):
            assert "definitely-not-it" not in json.dumps(row.details)
            assert "orbital-lantern" not in json.dumps(row.details)


def test_generated_key_mode_and_ndjson_stream(client, cover_png):
    token = make_user(client, "stream@example.com")
    response = client.post(
        "/api/steganography/embed",
        headers={**auth_header(token), "Accept": "application/x-ndjson"},
        files={"image": ("cover.png", cover_png, "image/png")},
        data={"algorithm": "dwt", "payload_type": "text", "message": "stream me", "key_mode": "generate"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "result"
    assert all(event["type"] == "log" for event in events[:-1])
    key = events[-1]["data"]["generated_key"]
    assert key.startswith("slk1_")

    stego = client.get(f"/api/artifacts/{events[-1]['data']['artifacts']['stego']}", headers=auth_header(token)).content
    recovered = client.post(
        "/api/steganography/extract",
        headers=auth_header(token),
        files={"image": ("stego.png", stego, "image/png")},
        data={"secret": key},
    ).json()["result"]
    assert recovered["payload"]["text"] == "stream me"


def test_file_payload_roundtrip(client, cover_png):
    token = make_user(client, "filepayload@example.com")
    blob = bytes(range(256)) * 8
    response = client.post(
        "/api/steganography/embed",
        headers=auth_header(token),
        files={"image": ("cover.png", cover_png, "image/png"), "payload_file": ("notes.bin", blob, "application/octet-stream")},
        data={"algorithm": "lsb", "payload_type": "file", "key_mode": "passphrase", "passphrase": "file-payload-pass"},
    )
    assert response.status_code == 200, response.text
    stego = client.get(f"/api/artifacts/{response.json()['result']['artifacts']['stego']}", headers=auth_header(token)).content
    recovered = client.post(
        "/api/steganography/extract",
        headers=auth_header(token),
        files={"image": ("s.png", stego, "image/png")},
        data={"secret": "file-payload-pass"},
    ).json()["result"]["payload"]
    import base64

    assert recovered["filename"] == "notes.bin"
    assert base64.b64decode(recovered["content_b64"]) == blob


def test_insufficient_capacity_is_reported(client):
    token = make_user(client, "tiny@example.com")
    tiny = _png(np.full((64, 64, 3), 128, dtype=np.uint8))
    response = client.post(
        "/api/steganography/embed",
        headers=auth_header(token),
        files={"image": ("tiny.png", tiny, "image/png")},
        data={"algorithm": "dwt", "payload_type": "text", "message": "x" * 100, "key_mode": "passphrase", "passphrase": "capacity-check-1"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_capacity"


@pytest.mark.parametrize(
    "filename,content,mime,code",
    [
        ("evil.exe", b"MZ\x90\x00", "application/octet-stream", "unsupported_image"),
        ("fake.png", b"\xff\xd8\xff\xe0" + b"0" * 100, "image/png", "unsupported_image"),  # JPEG bytes, .png name
        ("broken.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png", "corrupted_file"),
        ("empty.png", b"", "image/png", "validation_failed"),
    ],
)
def test_upload_validation(client, filename, content, mime, code):
    token = make_user(client, f"upload-{code}-{filename}@example.com")
    response = client.post(
        "/api/steganography/extract",
        headers=auth_header(token),
        files={"image": (filename, content, mime)},
        data={"algorithm": "auto"},
    )
    assert response.status_code in (415, 422), response.text
    assert response.json()["error"]["code"] == code


def test_truncated_png_is_rejected(client, cover_png):
    token = make_user(client, "truncated@example.com")
    response = client.post(
        "/api/steganography/extract",
        headers=auth_header(token),
        files={"image": ("t.png", cover_png[: len(cover_png) // 2], "image/png")},
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "corrupted_file"


def test_artifacts_are_private_to_their_owner(client, cover_png):
    owner = make_user(client, "owner@example.com")
    stranger = make_user(client, "stranger@example.com")
    artifact = _embed(client, owner, cover_png, "lsb").json()["result"]["artifacts"]["stego"]
    assert client.get(f"/api/artifacts/{artifact}", headers=auth_header(owner)).status_code == 200
    assert client.get(f"/api/artifacts/{artifact}", headers=auth_header(stranger)).status_code == 404
    assert client.get(f"/api/artifacts/{artifact}").status_code == 401


def test_capacity_endpoint_reports_all_algorithms(client, cover_png):
    token = make_user(client, "capacity@example.com")
    response = client.post(
        "/api/steganography/capacity", headers=auth_header(token), files={"image": ("c.png", cover_png, "image/png")}
    )
    assert response.status_code == 200
    caps = {row["algorithm"]: row for row in response.json()["algorithms"]}
    assert caps["lsb"]["slots"] == 512 * 512 * 3
    assert caps["lsb"]["max_payload_bytes"] > caps["dct"]["max_payload_bytes"] > caps["dwt"]["max_payload_bytes"] > 0
