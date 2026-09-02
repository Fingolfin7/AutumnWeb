import json
import os
import subprocess
import sys

from django.test import SimpleTestCase


class DatabaseSettingsTests(SimpleTestCase):
    @staticmethod
    def load_database_settings(
        database_url, *, disable_server_side_cursors=None, conn_max_age=None
    ):
        process_env = os.environ.copy()
        process_env["SECRET_KEY"] = "database-settings-test-key"
        process_env["DATABASE_URL"] = database_url
        if disable_server_side_cursors is None:
            process_env.pop("DISABLE_SERVER_SIDE_CURSORS", None)
        else:
            process_env["DISABLE_SERVER_SIDE_CURSORS"] = str(
                disable_server_side_cursors
            )
        if conn_max_age is None:
            process_env.pop("CONN_MAX_AGE", None)
        else:
            process_env["CONN_MAX_AGE"] = str(conn_max_age)

        command = """
import json
from unittest.mock import patch

with patch("environ.Env.read_env"):
    from django.conf import settings

    database = settings.DATABASES["default"]
    print(json.dumps({
        "conn_max_age": database.get("CONN_MAX_AGE"),
        "disable_server_side_cursors": database.get(
            "DISABLE_SERVER_SIDE_CURSORS"
        )
    }))
"""
        completed = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env=process_env,
        )
        return json.loads(completed.stdout)

    def test_neon_pooler_disables_server_side_cursors_by_default(self):
        database = self.load_database_settings(
            "postgresql://user:password@ep-example-pooler.eu.neon.tech/database"
        )

        self.assertIs(database["disable_server_side_cursors"], True)

    def test_direct_postgres_keeps_server_side_cursors_by_default(self):
        database = self.load_database_settings(
            "postgresql://user:password@ep-example.eu.neon.tech/database"
        )

        self.assertIs(database["disable_server_side_cursors"], False)

    def test_environment_can_override_pooler_default(self):
        database = self.load_database_settings(
            "postgresql://user:password@ep-example-pooler.eu.neon.tech/database",
            disable_server_side_cursors=False,
        )

        self.assertIs(database["disable_server_side_cursors"], False)

    def test_connection_age_defaults_inside_database_alias(self):
        database = self.load_database_settings("sqlite:///settings-test.sqlite3")

        self.assertEqual(database["conn_max_age"], 60)

    def test_connection_age_environment_override_can_disable_persistence(self):
        database = self.load_database_settings(
            "sqlite:///settings-test.sqlite3", conn_max_age=0
        )

        self.assertEqual(database["conn_max_age"], 0)
