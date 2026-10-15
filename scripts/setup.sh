#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
from pathlib import Path
import secrets
path=Path('.env')
if not path.exists():
    password=secrets.token_hex(24)
    path.write_text(f'POSTGRES_PASSWORD={password}\nDATABASE_URL=postgresql://intelligence:{password}@127.0.0.1:55432/intelligence\n')
    path.chmod(0o600)
PY
python3 -m venv /tmp/prospect-intelligence-venv
/tmp/prospect-intelligence-venv/bin/pip install -r requirements.txt
docker compose up -d --wait
scripts/local.sh -m app.cli migrate
