from __future__ import annotations

import hashlib

import pytest

from app.core.errors import DecryptionFailure, ValidationFailed
from app.services import crypto
from app.services.crypto import KdfParams, PayloadKind, Secret

FAST = KdfParams(time_cost=1, memory_kib=8192, parallelism=1)


def test_sha256_known_vector():
    # FIPS 180-2 test vector
    assert crypto.sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_passphrase_roundtrip_text():
    secret = Secret(passphrase="correct horse battery")
    result = crypto.encrypt_payload("Meet at dawn — Ω".encode(), secret, kdf_params=FAST)
    assert result.envelope[:4] == b"SLE1"
    assert result.envelope_sha256 == hashlib.sha256(result.envelope).hexdigest()
    payload = crypto.decrypt_envelope(result.envelope, secret)
    assert payload.kind == PayloadKind.TEXT
    assert payload.text == "Meet at dawn — Ω"
    assert payload.integrity_verified
    assert payload.content_sha256 == result.content_sha256


def test_file_roundtrip_preserves_name_and_bytes():
    key, encoded = crypto.generate_raw_key()
    assert crypto.parse_raw_key(encoded) == key
    blob = bytes(range(256)) * 40
    result = crypto.encrypt_payload(blob, Secret(raw_key=key), kind=PayloadKind.FILE, filename="../../etc/report.pdf")
    payload = crypto.decrypt_envelope(result.envelope, crypto.secret_from_user_input(encoded))
    assert payload.content == blob
    assert payload.filename == "report.pdf"  # path components stripped


def test_compression_used_only_when_smaller():
    secret = Secret(raw_key=bytes(32))
    assert crypto.encrypt_payload(b"A" * 5000, secret).compressed is True
    import os

    assert crypto.encrypt_payload(os.urandom(500), secret).compressed is False


def test_wrong_passphrase_fails_safely():
    envelope = crypto.encrypt_payload(b"secret", Secret(passphrase="right-passphrase"), kdf_params=FAST).envelope
    with pytest.raises(DecryptionFailure):
        crypto.decrypt_envelope(envelope, Secret(passphrase="wrong-passphrase"))


def test_key_type_mismatch_is_reported():
    envelope = crypto.encrypt_payload(b"secret", Secret(passphrase="right-passphrase"), kdf_params=FAST).envelope
    with pytest.raises(DecryptionFailure, match="passphrase"):
        crypto.decrypt_envelope(envelope, Secret(raw_key=bytes(32)))


@pytest.mark.parametrize("offset", [11, 30, 45, -1])  # salt, nonce, ciphertext, tag
def test_any_tampering_is_detected(offset):
    secret = Secret(passphrase="tamper-test-pass")
    envelope = bytearray(crypto.encrypt_payload(b"integrity matters", secret, kdf_params=FAST).envelope)
    envelope[offset] ^= 0x01
    with pytest.raises(DecryptionFailure):
        crypto.decrypt_envelope(bytes(envelope), secret)


def test_nonce_and_salt_are_fresh_per_encryption():
    secret = Secret(passphrase="same-passphrase")
    a = crypto.encrypt_payload(b"same", secret, kdf_params=FAST).envelope
    b = crypto.encrypt_payload(b"same", secret, kdf_params=FAST).envelope
    assert a[11:27] != b[11:27]  # salt
    assert a[27:39] != b[27:39]  # nonce
    assert a != b


def test_header_with_absurd_kdf_parameters_is_rejected():
    secret = Secret(passphrase="dos-guard-pass")
    envelope = bytearray(crypto.encrypt_payload(b"x", secret, kdf_params=FAST).envelope)
    envelope[6:10] = (4 * 1024 * 1024).to_bytes(4, "big")  # 4 GiB memory cost
    with pytest.raises(DecryptionFailure, match="out-of-range"):
        crypto.decrypt_envelope(bytes(envelope), secret)


def test_production_argon2id_parameters_derive_256_bit_key():
    params = KdfParams(time_cost=3, memory_kib=65536, parallelism=4)
    key = crypto.derive_key("production-strength", b"\x00" * 16, params)
    assert len(key) == 32
    assert key == crypto.derive_key("production-strength", b"\x00" * 16, params)
    assert key != crypto.derive_key("production-strength", b"\x01" * 16, params)


def test_user_input_validation():
    with pytest.raises(ValidationFailed):
        crypto.secret_from_user_input("short")
    with pytest.raises(ValidationFailed):
        crypto.secret_from_user_input("slk1_not-a-valid-key")
    assert crypto.secret_from_user_input("long enough pass").passphrase == "long enough pass"
    assert "***" in repr(Secret(passphrase="never-print-me")) and "never-print-me" not in repr(
        Secret(passphrase="never-print-me")
    )
