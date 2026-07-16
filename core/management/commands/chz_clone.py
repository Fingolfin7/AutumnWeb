"""Create a read-only SQLite backup for local characterization tests."""

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Clone the live SQLite DB via the backup API for characterization tests."

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("chz_clone requires the default database engine to be sqlite3")
        source = Path(settings.BASE_DIR) / "db.sqlite3"
        if not source.is_file():
            raise CommandError("db.sqlite3 is missing from the repository root")

        directory = Path(settings.BASE_DIR) / "characterization"
        directory.mkdir(parents=True, exist_ok=True)
        clone = directory / "clone.sqlite3"
        meta_path = directory / "meta.json"
        temp_clone = directory / (".clone-%s.tmp" % uuid.uuid4())
        temp_meta = directory / (".meta-%s.tmp" % uuid.uuid4())
        try:
            with closing(sqlite3.connect("file:db.sqlite3?mode=ro", uri=True)) as src:
                with closing(sqlite3.connect(str(temp_clone))) as dst:
                    src.backup(dst)
            with closing(
                sqlite3.connect("file:%s?mode=ro" % temp_clone.as_posix(), uri=True)
            ) as db:
                row = db.execute(
                    "SELECT u.username, COUNT(s.id) AS session_count "
                    "FROM auth_user u LEFT JOIN core_sessions s ON s.user_id = u.id "
                    "GROUP BY u.id, u.username ORDER BY session_count DESC, u.username ASC LIMIT 1"
                ).fetchone()
            if not row:
                raise CommandError("the cloned database contains no users")
            meta = {
                "clone_id": str(uuid.uuid4()),
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "username": row[0],
            }
            temp_meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            os.replace(temp_clone, clone)
            os.replace(temp_meta, meta_path)
        except Exception:
            for path in (temp_clone, temp_meta):
                try:
                    path.unlink()
                except (FileNotFoundError, PermissionError):
                    pass
            raise
        self.stdout.write(
            self.style.SUCCESS(
                "Created %s and %s for user %s (clone_id %s)"
                % (clone, meta_path, meta["username"], meta["clone_id"])
            )
        )
