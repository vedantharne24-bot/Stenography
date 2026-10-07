# API reference

Base path `/api`. Interactive OpenAPI docs: `http://localhost:8000/docs` (disabled in production).
All errors share one shape:

```json
{ "error": { "code": "insufficient_capacity", "message": "Payload needs …", "details": { } } }
```

Codes: `validation_failed` 422 · `unsupported_image` 415 · `corrupted_file` 422 · `payload_too_large` 413 ·
`insufficient_capacity` 422 · `integrity_failure` 422 · `decryption_failed` 422 · `unauthorized`/`invalid_credentials`/`token_expired` 401 ·
`forbidden` 403 · `not_found` 404 · `conflict` 409 · `rate_limited` 429 (`Retry-After`) · `model_unavailable` 503 · `internal_error` 500 (incident id).

## Authentication

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/auth/register` | `{name, email, password}` | 201 → `TokenResponse`; sets refresh cookie |
| POST | `/auth/login` | `{email, password}` | `TokenResponse`; rate-limited; lockout after 5 failures |
| POST | `/auth/refresh` | — (cookie) | requires `X-Requested-With: stegolab`; rotates the refresh token |
| POST | `/auth/logout` | — | requires `X-Requested-With`; revokes the session |
| GET/PATCH | `/auth/me` | `{name}` | current user + permissions |
| POST | `/auth/change-password` | `{current_password, new_password}` | revokes all sessions |

`TokenResponse = {access_token, token_type: "bearer", expires_in, user}`. Send
`Authorization: Bearer <access_token>` on every other call.

## Streaming operations

Long operations accept `Accept: application/x-ndjson` and then stream one JSON object per line:

```
{"type":"log","ts":"2026-10-07T08:02:48.912+00:00","elapsed_ms":15.2,"stage":"validate","level":"info","message":"Validating cover image complete","data":{"duration_ms":15.0}}
…
{"type":"result","data":{…}}            // or {"type":"error","status":422,"error":{…}}
```

Without that header they return `{"result": …, "trace": [log events…]}`.

## Steganography (`stego:embed` / `stego:extract`)

| Method | Path | Form fields |
|---|---|---|
| POST | `/steganography/capacity` | `image` → capacity per algorithm |
| POST | `/steganography/encrypt` | `payload_type` (text\|file), `message` or `payload_file`, `key_mode` (passphrase\|generate\|key), `passphrase` → envelope (base64) + hashes |
| POST | `/steganography/embed` ⟳ | `image`, `algorithm` (lsb\|dct\|dwt), payload fields, key fields → stego artefact, MSE/PSNR/SSIM, capacity, utilisation, hashes, one-time generated key |
| POST | `/steganography/extract` ⟳ | `image`, `algorithm` (auto\|lsb\|dct\|dwt), `secret` (optional) → detected format, integrity, decryption, payload |
| POST | `/steganography/decrypt` ⟳ | JSON `{envelope_b64, secret}` |
| GET | `/steganography/algorithms` | algorithm parameters |

⟳ = supports NDJSON streaming.

## Analysis

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/steganalysis/analyze` ⟳ | analysis:run | `image`, `explain` → prediction, probabilities (CNN + RF), anomaly, risk + factors, Grad-CAM artefacts, tile map, model version |
| POST | `/steganalysis/explain` ⟳ | analysis:run | same with explanation forced |
| POST | `/forensics/analyze` ⟳ | forensics:run | metadata, entropy, histograms, pixel stats, χ²/SPA, DCT/DWT statistics, visual attacks, findings, AI verdict |
| GET | `/attacks/catalogue` | attacks:run | attack types, parameter ranges, default suite |
| POST | `/attacks/run` ⟳ | attacks:run | `image`, `attack`, `params` (JSON), `secret` → before/after detection, extraction, integrity, BER, quality |
| POST | `/attacks/batch` ⟳ | attacks:run | `image`, `suite` (JSON list, optional), `secret` |
| POST | `/experiments/run` ⟳ | experiments:run | JSON `{images, payload_mode, relative, absolute_bytes, seed, weights}` |
| GET | `/experiments`, `/experiments/{id}` | experiments:run | stored research runs |

## Records

| Method | Path | Permission |
|---|---|---|
| GET | `/dashboard/stats?scope=&days=` | any (global scope needs dashboard:global) |
| GET | `/history?kind=analysis\|operation\|attack&page=&page_size=&q=&all_users=` | history:own (all_users → history:all) |
| GET | `/history/analysis/{id}` | owner / history:all |
| DELETE | `/history/{kind}/{id}`, `/history` | owner (erasure; audit kept) |
| POST | `/reports/{analysis_id}` | reports:generate → PDF report record |
| GET | `/reports`, `/reports/{id}`, `/reports/{id}/download` | reports:generate (owner) |
| DELETE | `/reports/{id}` | owner |
| GET | `/models`, `/models/{id}/metrics` | models:read |
| POST | `/models/{id}/activate` | models:manage |
| GET | `/audit-logs?action=&result=&user_query=&since=&page=` | audit:read |
| GET | `/admin/users`, PATCH `/admin/users/{id}` `{role, is_active}` | users:manage |
| GET/PATCH | `/admin/settings` | settings:manage |
| POST | `/admin/retention/sweep` | settings:manage |
| GET | `/artifacts/{id}?download=` | owner |

## Public (no authentication)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | DB status, compute device, active model versions |
| GET | `/public/overview` | active model metrics, aggregate counters, dataset stats, latest research run |
| POST | `/public/demo` | `{algorithm}` — server-side live demo on a held-out test image; nothing stored; rate-limited |

## Example (curl)

```bash
TOKEN=$(curl -s localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"…"}' | jq -r .access_token)

curl -s localhost:8000/api/steganography/embed -H "Authorization: Bearer $TOKEN" \
  -F image=@cover.png -F algorithm=dct -F payload_type=text -F message='hello' \
  -F key_mode=passphrase -F passphrase='correct horse battery' | jq .result.quality

curl -N localhost:8000/api/steganalysis/analyze -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: application/x-ndjson' -F image=@suspect.png
```
