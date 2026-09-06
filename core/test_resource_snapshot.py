from django.test import SimpleTestCase

from scripts.resource_snapshot import counter_delta


class ResourceCounterTests(SimpleTestCase):
    def test_reset_or_missing_period_cannot_be_reported_as_savings(self):
        for before, after in (
            ({}, {}),
            ({"consumption_period_start": "September"}, {"consumption_period_start": "October"}),
        ):
            with self.subTest(before=before, after=after):
                self.assertIn("unavailable", counter_delta(before, after))

    def test_counter_deltas_preserve_missing_and_decreasing_as_unknown(self):
        before = {"consumption_period_start": "September", "compute_time_seconds": 10, "data_transfer_bytes": 100}
        after = {"consumption_period_start": "September", "compute_time_seconds": 30, "data_transfer_bytes": 50}
        result = counter_delta(before, after)
        self.assertEqual(result["compute_time_seconds"], 20)
        self.assertIsNone(result["data_transfer_bytes"])
        self.assertIsNone(result["written_data_bytes"])
