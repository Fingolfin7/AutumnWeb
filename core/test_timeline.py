"""Tests for core.timeline.build_day_timeline.

The hazards here are geometry ones that look plausible when wrong: a block
40px off still renders as a block. So these assert positions numerically
rather than just checking that something came back.
"""

from datetime import date, datetime, time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Projects, Sessions, SubProjects
from core.timeline import MIN_GAP_MINUTES, build_day_timeline, build_timeline

DAY = date(2026, 7, 25)


def _at(hour, minute=0, day=DAY):
    return timezone.make_aware(datetime.combine(day, time(hour=hour, minute=minute)))


class TimelineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="finrod", password="pw")
        cls.atlas = Projects.objects.create(user=cls.user, name="Atlas API")
        cls.autumn = Projects.objects.create(user=cls.user, name="Autumn")

    def _session(self, project, start, end, subs=(), user=None):
        session = Sessions.objects.create(
            user=user or self.user, project=project, start_time=start, end_time=end
        )
        for name in subs:
            sub, _ = SubProjects.objects.get_or_create(
                user=self.user, parent_project=project, name=name
            )
            session.subprojects.add(sub)
        return session


class WindowTests(TimelineTestCase):
    def test_default_window_when_sessions_fall_inside_it(self):
        self._session(self.atlas, _at(9), _at(10))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["window_start_hour"], 6)
        self.assertEqual(tl["window_end_hour"], 22)

    def test_window_widens_for_an_early_session(self):
        """A 03:00 session must be visible, not clipped off the left edge."""
        self._session(self.atlas, _at(3), _at(4))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["window_start_hour"], 3)

    def test_window_widens_for_a_late_session(self):
        self._session(self.atlas, _at(22, 10), _at(23, 30))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["window_end_hour"], 24)

    def test_partial_end_hour_rounds_up(self):
        """Ending at 22:30 needs the axis to reach 23, or the block overflows."""
        self._session(self.atlas, _at(21), _at(22, 30))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["window_end_hour"], 23)


class GeometryTests(TimelineTestCase):
    def test_block_position_is_a_percentage_of_the_window(self):
        # 06:00-22:00 window = 960 minutes. 09:00 is 180 min in = 18.75%.
        # A 96-minute session is 10% wide.
        self._session(self.atlas, _at(9), _at(10, 36))
        tl = build_day_timeline(self.user, DAY)
        block = tl["lanes"][0]["blocks"][0]
        self.assertAlmostEqual(block["start_pct"], 18.75, places=3)
        self.assertAlmostEqual(block["width_pct"], 10.0, places=3)

    def test_hour_ticks_span_the_full_axis(self):
        self._session(self.atlas, _at(9), _at(10))
        tl = build_day_timeline(self.user, DAY)
        self.assertAlmostEqual(tl["ticks"][0]["x_pct"], 0.0)
        self.assertAlmostEqual(tl["ticks"][-1]["x_pct"], 100.0)
        self.assertEqual(tl["ticks"][0]["label"], "06")

    def test_midnight_hour_label_wraps_to_00(self):
        self._session(self.atlas, _at(23), _at(23, 59))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["ticks"][-1]["label"], "00")


class ClippingTests(TimelineTestCase):
    def test_session_crossing_midnight_is_clipped_to_the_day(self):
        """Started 23:00 yesterday, ended 01:00 today -> today shows 00:00-01:00."""
        self._session(
            self.atlas,
            _at(23, day=DAY - timedelta(days=1)),
            _at(1),
        )
        tl = build_day_timeline(self.user, DAY)
        block = tl["lanes"][0]["blocks"][0]
        self.assertAlmostEqual(block["start_pct"], 0.0, places=3)
        self.assertEqual(block["start_local"].hour, 0)
        # 60 clipped minutes, not the full 120
        self.assertAlmostEqual(block["minutes"], 60.0, places=3)

    def test_session_wholly_on_another_day_is_excluded(self):
        self._session(self.atlas, _at(9, day=DAY - timedelta(days=3)), _at(10, day=DAY - timedelta(days=3)))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["lanes"], [])

    def test_other_users_sessions_are_excluded(self):
        intruder = User.objects.create_user(
            username="sauron", email="sauron@example.com", password="pw"
        )
        other_project = Projects.objects.create(user=intruder, name="Barad-dur")
        self._session(other_project, _at(9), _at(10), user=intruder)
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["lanes"], [])


class RunningTimerTests(TimelineTestCase):
    def test_running_timer_is_drawn_up_to_now(self):
        with mock.patch("django.utils.timezone.now", return_value=_at(17, 47)):
            self._session(self.atlas, _at(17), None)
            tl = build_day_timeline(self.user, DAY)
        block = tl["lanes"][0]["blocks"][0]
        self.assertTrue(block["is_live"])
        self.assertIsNone(block["end_local"])
        self.assertAlmostEqual(block["minutes"], 47.0, places=3)

    def test_live_minutes_are_reported_separately_from_closed_ones(self):
        with mock.patch("django.utils.timezone.now", return_value=_at(17, 30)):
            self._session(self.atlas, _at(9), _at(10))
            self._session(self.atlas, _at(17), None)
            tl = build_day_timeline(self.user, DAY)
        lane = tl["lanes"][0]
        self.assertAlmostEqual(lane["total_minutes"], 60.0, places=3)
        self.assertAlmostEqual(lane["live_minutes"], 30.0, places=3)


class NowMarkerTests(TimelineTestCase):
    def test_now_marker_positioned_on_today(self):
        # 17:47 in a 06:00-22:00 window = 707/960 = 73.6458%
        with mock.patch("django.utils.timezone.now", return_value=_at(17, 47)):
            with mock.patch("django.utils.timezone.localdate", return_value=DAY):
                self._session(self.atlas, _at(9), _at(10))
                tl = build_day_timeline(self.user, DAY)
        self.assertAlmostEqual(tl["now_pct"], 73.6458, places=3)
        self.assertEqual(tl["now_label"], "17:47")

    def test_no_now_marker_on_a_past_day(self):
        self._session(self.atlas, _at(9), _at(10))
        tl = build_day_timeline(self.user, DAY)  # DAY is not today
        self.assertIsNone(tl["now_pct"])
        self.assertIsNone(tl["now_label"])


class GapTests(TimelineTestCase):
    def test_gap_between_sessions_is_reported(self):
        self._session(self.atlas, _at(9), _at(10))
        self._session(self.atlas, _at(12), _at(13))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(len(tl["gaps"]), 1)
        self.assertEqual(tl["gaps"][0]["minutes"], 120)

    def test_short_gaps_are_ignored(self):
        self._session(self.atlas, _at(9), _at(10))
        self._session(self.atlas, _at(10, MIN_GAP_MINUTES - 5), _at(11))
        self.assertEqual(build_day_timeline(self.user, DAY)["gaps"], [])

    def test_overlapping_sessions_on_different_projects_do_not_make_a_gap(self):
        """Two timers running at once must not read as idle time between them."""
        self._session(self.atlas, _at(9), _at(12))
        self._session(self.autumn, _at(10), _at(11))
        self.assertEqual(build_day_timeline(self.user, DAY)["gaps"], [])


class LaneTests(TimelineTestCase):
    def test_lanes_are_ordered_by_time_spent(self):
        self._session(self.autumn, _at(9), _at(9, 30))
        self._session(self.atlas, _at(11), _at(14))
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual([lane["project"].name for lane in tl["lanes"]], ["Atlas API", "Autumn"])

    def test_each_lane_gets_a_distinct_colour(self):
        self._session(self.atlas, _at(9), _at(10))
        self._session(self.autumn, _at(11), _at(12))
        colours = [lane["colour"] for lane in build_day_timeline(self.user, DAY)["lanes"]]
        self.assertEqual(len(set(colours)), 2)

    def test_subproject_names_become_the_block_label(self):
        self._session(self.atlas, _at(9), _at(10), subs=["billing", "migrations"])
        block = build_day_timeline(self.user, DAY)["lanes"][0]["blocks"][0]
        self.assertEqual(sorted(block["label"].split(", ")), ["billing", "migrations"])

    def test_empty_day_returns_no_lanes_but_a_valid_axis(self):
        tl = build_day_timeline(self.user, DAY)
        self.assertEqual(tl["lanes"], [])
        self.assertEqual(tl["gaps"], [])
        self.assertEqual(tl["window_start_hour"], 6)
        self.assertTrue(tl["ticks"])


class DurationLabelTests(TimelineTestCase):
    """The chart labels its own figures, so they are part of its contract.

    Gap and block labels are drawn inside boxes a few dozen pixels wide, hence
    the compact "1h 08m" / "45m" form rather than the app's general duration
    filters.
    """

    def test_block_carries_a_compact_duration_label(self):
        self._session(self.atlas, _at(9), _at(10, 8))
        block = build_day_timeline(self.user, DAY)["lanes"][0]["blocks"][0]
        self.assertEqual(block["duration_label"], "1h 08m")

    def test_sub_hour_durations_drop_the_hour_component(self):
        self._session(self.atlas, _at(9), _at(9, 45))
        block = build_day_timeline(self.user, DAY)["lanes"][0]["blocks"][0]
        self.assertEqual(block["duration_label"], "45m")

    def test_gap_carries_a_compact_label(self):
        self._session(self.atlas, _at(9), _at(10))
        self._session(self.atlas, _at(12), _at(13))
        self.assertEqual(build_day_timeline(self.user, DAY)["gaps"][0]["label"], "2h 00m")

    def test_lane_totals_are_labelled_and_live_time_is_kept_separate(self):
        self._session(self.atlas, _at(9), _at(10, 30))
        tl = build_day_timeline(self.user, DAY)
        lane = tl["lanes"][0]
        self.assertEqual(lane["total_label"], "1h 30m")
        self.assertIsNone(lane["live_label"])

    def test_a_lane_with_only_a_running_timer_has_no_completed_total(self):
        """A fresh timer must not announce itself as "0m" tracked."""
        now = timezone.now()
        Sessions.objects.create(
            user=self.user, project=self.atlas, start_time=now - timedelta(minutes=20)
        )
        lane = build_day_timeline(self.user)["lanes"][0]
        self.assertIsNone(lane["total_label"])
        self.assertEqual(lane["live_label"], "20m")


class RangeTests(TimelineTestCase):
    """The 3-day and week views share the geometry engine but not the axis."""

    def test_a_multi_day_range_spans_whole_days(self):
        tl = build_timeline(self.user, "d3", end_day=DAY)
        self.assertEqual(tl["start_day"], DAY - timedelta(days=2))
        self.assertEqual(tl["date"], DAY)
        self.assertTrue(tl["is_multi_day"])
        self.assertIsNone(tl["window_start_hour"])

    def test_day_labels_are_centred_over_their_own_day(self):
        """A label sitting on midnight belongs to neither day it separates."""
        ticks = build_timeline(self.user, "d3", end_day=DAY)["ticks"]
        self.assertEqual(len(ticks), 3)
        self.assertAlmostEqual(ticks[0]["x_pct"], 100 / 3 / 2, places=2)
        self.assertAlmostEqual(ticks[-1]["x_pct"], 100 - 100 / 3 / 2, places=2)

    def test_sessions_from_earlier_days_appear_in_a_multi_day_range(self):
        self._session(self.atlas, _at(9, day=DAY - timedelta(days=2)),
                      _at(10, day=DAY - timedelta(days=2)))
        self._session(self.autumn, _at(9), _at(10))

        day_only = build_timeline(self.user, "today", end_day=DAY)
        three_days = build_timeline(self.user, "d3", end_day=DAY)

        self.assertEqual([l["project"].name for l in day_only["lanes"]], ["Autumn"])
        self.assertEqual(
            sorted(l["project"].name for l in three_days["lanes"]),
            ["Atlas API", "Autumn"],
        )

    def test_a_session_two_days_back_sits_in_the_first_third(self):
        self._session(self.atlas, _at(12, day=DAY - timedelta(days=2)),
                      _at(13, day=DAY - timedelta(days=2)))
        block = build_timeline(self.user, "d3", end_day=DAY)["lanes"][0]["blocks"][0]
        # 12:00 on day 1 of 3 == half a day into a three-day window
        self.assertAlmostEqual(block["start_pct"], 100 * 12 / 72, places=1)

    def test_overnight_is_not_reported_as_a_gap(self):
        """Nights are not untracked time worth labelling."""
        self._session(self.atlas, _at(9), _at(10))
        self._session(self.atlas, _at(9, day=DAY - timedelta(days=1)),
                      _at(10, day=DAY - timedelta(days=1)))
        self.assertEqual(build_timeline(self.user, "d3", end_day=DAY)["gaps"], [])

    def test_an_unknown_range_falls_back_to_today(self):
        """The range arrives from a query string and can be anything."""
        tl = build_timeline(self.user, "../etc/passwd", end_day=DAY)
        self.assertEqual(tl["range_key"], "today")
        self.assertFalse(tl["is_multi_day"])

    def test_tracked_total_matches_the_lanes_drawn(self):
        self._session(self.atlas, _at(9), _at(10))
        self._session(self.autumn, _at(11), _at(11, 30))
        tl = build_timeline(self.user, "today", end_day=DAY)
        self.assertAlmostEqual(tl["tracked_minutes"], 90.0)


class LiveBlockGeometryTests(TimelineTestCase):
    def test_a_live_block_ends_at_now_and_never_beyond(self):
        """Nothing may be drawn to the right of the now-marker: that is time
        which has not happened."""
        now = timezone.now()
        Sessions.objects.create(
            user=self.user, project=self.atlas, start_time=now - timedelta(seconds=20)
        )

        tl = build_timeline(self.user, "today")
        block = tl["lanes"][0]["blocks"][0]

        self.assertTrue(block["is_live"])
        self.assertAlmostEqual(block["end_pct"], tl["now_pct"], places=2)
        self.assertLessEqual(block["end_pct"], tl["now_pct"] + 0.01)

    def test_end_pct_is_start_plus_width(self):
        self._session(self.atlas, _at(9), _at(10))
        block = build_timeline(self.user, "today", end_day=DAY)["lanes"][0]["blocks"][0]
        self.assertAlmostEqual(
            block["end_pct"], block["start_pct"] + block["width_pct"], places=3
        )
