# Deployment

## Development (Windows / macOS / Linux)

```bash
# 1. Backend
cd backend
python -m venv .venv && .venv/Scripts/activate          # source .venv/bin/activate on macOS/Linux
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128   # or /whl/cpu
pip install -r requirements-dev.txt
cd .. && python scripts/init_env.py --postgres && cd backend   # writes backend/.env (+ scripts/setup_postgres.sql)
alembic upgrade head
python -m app.cli bootstrap-admin
uvicorn app.main:app --port 8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api to :8000)
```

### PostgreSQL locally

`python scripts/init_env.py --postgres` generates a random password for a dedicated `stegolab`
role and writes `scripts/setup_postgres.sql` (git-ignored). Run it once as the superuser, then
uncomment `DATABASE_URL` in `backend/.env` and migrate:

```bash
psql -U postgres -h localhost -f scripts/setup_postgres.sql
cd backend && alembic upgrade head && python -m app.cli bootstrap-admin
```

To move an existing development database (users, analyses, audit trail, …) from SQLite to
PostgreSQL in one step — migrations, data copy in foreign-key order, sequence reset, row-count
verification and the `.env` switch:

```bash
psql -U postgres -h localhost -f scripts/setup_postgres.sql
backend/.venv/Scripts/python scripts/migrate_to_postgres.py      # add --dry-run to preview
```

Without PostgreSQL the API falls back to SQLite at `backend/storage/stegolab.db` (same schema,
same migrations).

### Data & models

```bash
cd backend
python -m pipeline.generate_dataset            # ~4 min, ~10.9 GB under data/dataset (55,248 tiles)
python -m pipeline.train_model --model all     # RF ~5 min (CPU), StegoNet ~60-80 min (RTX 4060)
python -m pipeline.evaluate_model              # re-evaluate saved weights on the test split
python -m pipeline.run_experiments --images 200
```

Cover images: DIV2K train (`DIV2K_train_HR.zip`) and COCO val2017 (`val2017.zip`) extracted to
`data/covers/`. The API registers trained models on start-up (`python -m app.cli sync-models`
does it on demand).

## Production (Docker)

```bash
cp .env.example .env          # set POSTGRES_PASSWORD, SECRET_KEY, JWT_SECRET (≥ 32 chars), admin bootstrap
docker compose up --build -d
# http://localhost:8080
```

Services: `db` (PostgreSQL 17, persistent volume), `api` (FastAPI + StegoNet; runs
`alembic upgrade head` and the admin bootstrap on start; non-root user; health-checked), `web`
(nginx serving the built SPA and reverse-proxying `/api` with buffering disabled so operation
streams arrive live).

* **GPU inference:** build with `TORCH_INDEX=https://download.pytorch.org/whl/cu128` and enable
  the commented `deploy.resources` block (requires the NVIDIA container toolkit). CPU inference
  works everywhere; `/api/health` reports the active device.
* **HTTPS:** terminate TLS in front of `web` (or extend `nginx.conf`) and set
  `COOKIE_SECURE=true`, `CORS_ORIGINS=https://your-host`.
* **Workers:** run one API worker per container (the loaded model and the rate limiter are
  in-process). Scale horizontally behind a proxy that enforces rate limits.
* **Model updates:** models are mounted read-only from `backend/models`; drop a new version
  directory in, restart `api`, and activate it from the Models page.

The Docker files are provided and reviewed but were not executed on the development machine
(Docker was not installed there); the same commands run in CI or on any Docker host.
