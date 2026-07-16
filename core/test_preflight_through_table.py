"""Database-portable preflight assertions for the implicit M2M through table."""

from django.db import connection
from django.test import TestCase


class SessionsSubprojectsThroughTableTests(TestCase):
    def test_expected_constraints_and_indexes(self):
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(
                cursor, "core_sessions_subprojects"
            )
            constraints = connection.introspection.get_constraints(
                cursor, "core_sessions_subprojects"
            )

        id_column = next(column for column in description if column.name == "id")
        id_type = connection.introspection.get_field_type(
            id_column.type_code, id_column
        )
        self.assertIn(
            id_type, {"AutoField", "BigAutoField", "IntegerField", "BigIntegerField"}
        )

        primary = [item for item in constraints.values() if item.get("primary_key")]
        self.assertEqual(len(primary), 1)
        self.assertEqual(primary[0].get("columns"), ["id"])

        unique_columns = {
            tuple(item.get("columns") or [])
            for item in constraints.values()
            if item.get("unique") and not item.get("primary_key")
        }
        self.assertIn(("sessions_id", "subprojects_id"), unique_columns)

        indexed_columns = {
            tuple(item.get("columns") or [])
            for item in constraints.values()
            if item.get("index")
        }
        self.assertIn(("sessions_id",), indexed_columns)
        self.assertIn(("subprojects_id",), indexed_columns)

        foreign_keys = [item for item in constraints.values() if item.get("foreign_key")]
        if foreign_keys or connection.vendor == "postgresql":
            targets = {tuple(item["foreign_key"]) for item in foreign_keys}
            self.assertIn(("core_sessions", "id"), targets)
            self.assertIn(("core_subprojects", "id"), targets)
