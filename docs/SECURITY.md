# Security design

StegoLab applies least privilege, defence in depth and secure defaults. This document lists the
controls and where they are implemented (paths relative to `backend/`).

## Authentication

| Control | Implementation |
|---|---|
| Password storage | Argon2id (t=3, m=64 MiB, p=4, 16-byte salt) via `argon2-cffi`; transparent re-hash on parameter change — `app/core/security.py` |
| Password policy | ≥ 10 chars, 3 of 4 character classes, must not contain the email name (mirrored in the UI for feedback; enforced server-side) |
| Enumeration resistance | identical error for unknown account / wrong password; dummy Argon2 verification equalises timing |
| Brute force | per-IP sliding-window rate limit on `/api/auth/*`; account lockout after 5 failures for 15 min (audited) |
| Access tokens | HS256 JWT, 15 min, carries `sub`, `role`, `tv` (token version); kept **in memory** by the SPA |
| Refresh tokens | 256-bit random, stored only as HMAC-SHA-256 (keyed with `SECRET_KEY`); httpOnly, `SameSite=Strict`, path `/api/auth`, `Secure` behind HTTPS |
| Rotation & theft detection | every refresh rotates the token; replaying a rotated-out token revokes **all** of the user's sessions (`TOKEN_REUSE_DETECTED`) |
| CSRF | refresh/logout require the custom `X-Requested-With: stegolab` header (cannot be sent cross-site without a CORS pre-flight) in addition to SameSite=Strict |
| Revocation | password change or role/status change increments `token_version`, invalidating outstanding access tokens immediately |

## Authorization (RBAC)

Permissions are checked **server-side on every request** by the `require(Permission.X)`
dependency (`app/api/deps.py`); denials return 403 and are audited as `ACCESS_DENIED`. The
SPA hides/locks navigation only for usability.

| Permission | USER | ANALYST | ADMIN |
|---|:-:|:-:|:-:|
| stego:embed, stego:extract, analysis:run, history:own | ✓ | ✓ | ✓ |
| forensics:run, attacks:run, experiments:run, reports:generate, models:read, dashboard:global |  | ✓ | ✓ |
| history:all, models:manage, users:manage, audit:read, settings:manage |  |  | ✓ |

Object-level checks: artefacts, analyses, operations, attack records and reports are returned
only to their owner (admins via `history:all`); other users receive **404** (existence is not
revealed). Administrators cannot demote or disable themselves.

## Input validation & file handling (`app/services/image_io.py`)

1. Upload streamed with a hard byte limit (`MAX_UPLOAD_SIZE`); oversized `Content-Length` is
   rejected before reading.
2. Extension allow-list (PNG, JPEG, BMP, WEBP, TIFF).
3. Magic-byte sniffing — content must match the extension; declared MIME must match content.
4. Decompression-bomb guard (`Image.MAX_IMAGE_PIXELS`, warnings treated as errors) and
   dimension bounds (64–8192 px).
5. `Image.verify()` + full decode to catch corruption/truncation.
6. Animated/multi-frame images rejected.

Generated files get random UUID names under a server-controlled directory; the resolved path is
checked to stay inside the storage root. Output PNGs keep only the ICC profile — EXIF and text
metadata are stripped (privacy). Pydantic validates every JSON body and form field.

## Transport & headers

`Content-Security-Policy: default-src 'none'` on API responses, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, COOP, and HSTS when
`COOKIE_SECURE=true`. Strict CORS allow-list. The nginx front-end adds a CSP for the SPA. API docs
(`/docs`) are disabled in production.

## Secrets & sensitive data

* Secrets come from environment / `.env` only; the API refuses to start in production without
  ≥ 32-character `SECRET_KEY` and `JWT_SECRET`. `.env` and the generated DB script are git-ignored.
* **Never stored or logged:** passwords (only Argon2id hashes), encryption keys/passphrases,
  secret messages and recovered plaintext. Recovered payloads are returned inline and not
  written to disk. Generated keys are shown once.
* The audit writer scrubs any metadata key resembling a password/key/token/message before
  writing (`app/services/audit.py`); tests assert that secrets never appear in audit rows.

## Error handling

Domain errors map to typed JSON (`{"error": {"code", "message", "details"}}`); unexpected
exceptions return a generic 500 with an incident id while the stack trace is logged server-side
only. Streaming operations report errors as an `error` event.

## Audit logging

Append-only `audit_logs` table: `REGISTER`, `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOGOUT`,
`TOKEN_REFRESH`, `TOKEN_REUSE_DETECTED`, `PASSWORD_CHANGED`, `ACCESS_DENIED`, `IMAGE_ANALYSIS`,
`MODEL_USED`, `FORENSIC_ANALYSIS`, `ENCRYPTION`, `EMBEDDING`, `EXTRACTION`, `INTEGRITY_FAILURE`,
`DECRYPTION_SUCCESS`, `DECRYPTION_FAILURE`, `ATTACK_RUN`, `ATTACK_BATCH`, `EXPERIMENT_RUN`,
`REPORT_GENERATED`, `REPORT_DOWNLOADED`, `ARTIFACT_DOWNLOADED`, `DATA_DELETED`, `USER_UPDATED`,
`SETTINGS_CHANGED`, `MODEL_ACTIVATED`, `RETENTION_SWEEP`. Viewer: `/audit-logs` (admin).

## Privacy & retention — data classes

| Class | Examples | Lifetime |
|---|---|---|
| Temporary artefacts | previews, stego images, heat-maps, attacked images | expire after `temp_retention_hours` (default 24 h, admin-configurable); background sweeper every 30 min |
| User-owned records | analyses, operations, attack/research runs, PDF reports | until the owner deletes them (per item or "delete all my data") |
| Audit records | security events | retained; contain no secrets |
| Never persisted | plaintext payloads, keys, passwords | — |

## Known limitations

* The rate limiter is in-process (one API worker). Multi-worker deployments should enforce rate
  limits at the reverse proxy or move the store to Redis.
* Steganography confidentiality relies on AES-GCM; the embedding positions are public by design
  (Kerckhoffs). Statistical undetectability is measured, not assumed — see the research page.
