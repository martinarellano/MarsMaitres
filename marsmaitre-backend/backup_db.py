#!/usr/bin/env python3
"""Crea un respaldo consistente de SQLite para ejecutarse desde un job seguro."""
import os, sqlite3
from datetime import datetime, timezone
from pathlib import Path

source=Path(os.environ.get('MARSMAITRE_DB_PATH', '/data/marsmaitre.db'))
destination_dir=Path(os.environ.get('MARSMAITRE_BACKUP_DIR', '/data/backups'))
destination_dir.mkdir(parents=True, exist_ok=True)
if not source.exists():
    raise SystemExit(f'No existe la base: {source}')
name=f"marsmaitre-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
target=destination_dir/name
src=sqlite3.connect(source)
dst=sqlite3.connect(target)
try:
    src.backup(dst)
finally:
    dst.close(); src.close()
print(target)
