Local Postgres setup for development

This project expects a Postgres database for full functionality. A development Postgres is not installed/managed by `pip` or `requirements.txt` — those only install Python packages. To run a local Postgres for development you have two simple and common options below.

1) Recommended: start Postgres via Docker Compose (fast, isolated)

Prerequisites:
- Docker Desktop installed: https://www.docker.com/get-started

Commands (run from the repo root):

```bash
# Bring up only the db service in the background
docker compose up -d db

# Show service status
docker compose ps

# Tail db logs
docker compose logs -f db
```

Verify Postgres is accepting connections on localhost:5432:

```bash
# If you have pg_isready installed
pg_isready -h localhost -p 5432

# Or from Python (venv):
/Users/larryroberts/Documents/git/image-processor/venv/bin/python -c "import socket; s=socket.socket(); print(s.connect_ex(('127.0.0.1',5432)))"
# 0 means connection accepted; non-zero means not reachable
```

After Postgres is running you can initialize the schema (optional):

```bash
# Using the included helper script (will use DATABASE_URL, PG_DSN or DB_* env vars if present)
python3 scripts/init_postgres.py
```

2) Alternative: install Postgres locally with Homebrew (macOS)

```bash
# Install
brew install postgresql

# Start as a service
brew services start postgresql

# Create DB and user (optional)
createuser -s photo_user || true
createdb photo_analyzer || true
psql -c "ALTER USER photo_user WITH PASSWORD 'photo_password';"
```

Notes about `requirements.txt` and system services
-------------------------------------------------
- `requirements.txt` (and pip) install Python packages only (e.g. `psycopg2-binary` which is already included in this repo) and cannot install or start system services such as Postgres.
- The repo already contains a `docker-compose.yml` that defines a Postgres service (image: postgres:15). Starting that with Docker is the simplest way to get a local DB that matches the app's expectations.

Troubleshooting and verification
--------------------------------
- If you see "connection refused" errors when the app tries to connect, confirm Postgres is listening on 5432 with `lsof -iTCP:5432 -sTCP:LISTEN -Pn`.
- If `pg_isready` is missing you can install the postgres client tools or use Python socket checks (see above).

If you'd like, I can:
- Start the docker-compose Postgres for you (if Docker Desktop is installed on your machine).
- Attempt to install Postgres via Homebrew automatically (requires your consent).
- Add a small startup script that checks Postgres and prints helpful instructions.

Tell me which option you'd like me to take next.