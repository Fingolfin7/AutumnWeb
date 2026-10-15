"""Back up the local SQLite database before migrating it.

Uses SQLite's backup API, so changes still in the -wal file are included
(a plain file copy can miss them). Prints the backup's path.

Usage: python scripts/backup_sqlite.py
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AutumnWeb.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402


def main() -> int:
    database = settings.DATABASES["default"]
    if "sqlite" not in database["ENGINE"]:
        print("The database is not SQLite; back it up with its own tools.")
        return 1
    source = Path(database["NAME"])
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    target = source.with_name(f"{source.name}.bak-{stamp}")
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    with sqlite3.connect(target) as check:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        print(f"The backup at {target} failed its integrity check: {result}")
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
