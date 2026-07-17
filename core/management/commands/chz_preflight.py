"""Record through-table database constraints for modernization preflight."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


TABLE = "core_sessions_subprojects"


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class Command(BaseCommand):
    help = (
        "Merge the current vendor's through-table constraints into "
        "characterization/preflight_schema.json. Run again in a PostgreSQL "
        "environment later to add the postgres section."
    )

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, TABLE)
            payload = {"constraints": json_safe(constraints)}
            if connection.vendor == "sqlite":
                index_list = cursor.execute('PRAGMA index_list("%s")' % TABLE).fetchall()
                indexes = []
                for row in index_list:
                    info = cursor.execute('PRAGMA index_info("%s")' % row[1]).fetchall()
                    indexes.append({"index_list": list(row), "index_info": [list(item) for item in info]})
                payload["pragma_indexes"] = indexes

        path = Path(settings.BASE_DIR) / "characterization" / "preflight_schema.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        existing[connection.vendor] = payload
        path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS("Recorded %s constraints in %s" % (connection.vendor, path)))
