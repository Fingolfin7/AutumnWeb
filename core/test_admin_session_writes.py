"""Admin session write-path integrity (Finding 4).

Direct admin session edits and inline allocation edits must stay versioned and
commitment-safe even though they bypass SessionMutationService.
"""

from datetime import timezone as datetime_timezone

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils import timezone

from core.admin import SessionsAdmin
from core.models import Commitment, Projects, Sessions, SubProjects
from core.services import SessionMutationService


class _RequestFactoryMixin:
    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="owner", password="pw")
        self.project = Projects.objects.create(name="Proj", user=self.user)
        self.subproject = SubProjects.objects.create(
            name="Sub", user=self.user, parent_project=self.project
        )
        self.commitment = Commitment.objects.create(
            user=self.user,
            project=self.project,
            commitment_type="time",
            period="weekly",
            target=300,
        )

    def _make_session(self):
        return SessionMutationService.create_session(
            user=self.user,
            project=self.project,
            start_time=timezone.now(),
            end_time=timezone.now(),
            allocations=[(self.subproject, 10000)],
        )


class AdminSaveModelTests(_RequestFactoryMixin, TestCase):
    def _request(self):
        request = self.factory.post("/admin/core/sessions/")
        request.user = self.user
        return request

    def test_save_model_bumps_version_and_marks_commitment(self):
        session = self._make_session()
        version_before = session.version
        Commitment.objects.filter(pk=self.commitment.pk).update(needs_recompute=False)

        admin = SessionsAdmin(Sessions, AdminSite())
        session.note = "edited via admin"
        admin.save_model(self._request(), session, form=None, change=True)

        session.refresh_from_db()
        self.commitment.refresh_from_db()
        self.assertEqual(session.version, version_before + 1)
        self.assertTrue(self.commitment.needs_recompute)

    def test_save_model_floors_subsecond_start_time(self):
        session = self._make_session()
        # Push a sub-second start_time straight onto the instance, as a raw admin
        # edit would, and confirm save_model floors it to the whole second.
        session.start_time = session.start_time.replace(microsecond=123456)

        admin = SessionsAdmin(Sessions, AdminSite())
        admin.save_model(self._request(), session, form=None, change=True)

        session.refresh_from_db()
        self.assertEqual(session.start_time.microsecond, 0)


class _FakeFormset:
    def __init__(self, model, instance, new=(), changed=(), deleted=()):
        self.model = model
        self.instance = instance
        self.new_objects = list(new)
        self.changed_objects = list(changed)
        self.deleted_objects = list(deleted)

    def save(self, commit=True):
        return []


class _FakeForm:
    def __init__(self, instance):
        self.instance = instance


class AdminSaveFormsetTests(_RequestFactoryMixin, TestCase):
    def _request(self):
        request = self.factory.post("/admin/core/sessions/")
        request.user = self.user
        return request

    def test_inline_change_bumps_version_and_marks_dirty(self):
        from core.models import SessionSubproject

        session = self._make_session()
        version_before = session.version
        Commitment.objects.filter(pk=self.commitment.pk).update(needs_recompute=False)

        # Simulate an inline allocation edit having been applied.
        SessionSubproject.objects.filter(session=session).update(allocation_bp=5000)

        admin = SessionsAdmin(Sessions, AdminSite())
        formset = _FakeFormset(SessionSubproject, session, changed=[object()])
        admin.save_formset(self._request(), _FakeForm(session), formset, change=True)

        session.refresh_from_db()
        self.commitment.refresh_from_db()
        self.assertEqual(session.version, version_before + 1)
        self.assertTrue(self.commitment.needs_recompute)

    def test_inline_no_change_is_a_noop(self):
        from core.models import SessionSubproject

        session = self._make_session()
        version_before = session.version
        Commitment.objects.filter(pk=self.commitment.pk).update(needs_recompute=False)

        admin = SessionsAdmin(Sessions, AdminSite())
        formset = _FakeFormset(SessionSubproject, session)
        admin.save_formset(self._request(), _FakeForm(session), formset, change=True)

        session.refresh_from_db()
        self.commitment.refresh_from_db()
        self.assertEqual(session.version, version_before)
        self.assertFalse(self.commitment.needs_recompute)

    def test_inline_invalid_allocation_raises(self):
        from core.models import SessionSubproject

        session = self._make_session()
        # Over-allocate a session; validation must reject it.
        second_sub = SubProjects.objects.create(
            name="Sub2", user=self.user, parent_project=self.project
        )
        SessionSubproject.objects.filter(session=session).update(allocation_bp=10000)
        SessionSubproject.objects.create(
            session=session, subproject=second_sub, allocation_bp=10000
        )

        admin = SessionsAdmin(Sessions, AdminSite())
        formset = _FakeFormset(SessionSubproject, session, changed=[object()])
        with self.assertRaises(ValidationError):
            admin.save_formset(self._request(), _FakeForm(session), formset, change=True)


class AdminChangePostTests(_RequestFactoryMixin, TestCase):
    """At least one path exercised through a real admin POST."""

    def setUp(self):
        super().setUp()
        self.superuser = User.objects.create_superuser(
            username="admin", password="pw", email="a@b.co"
        )
        self.client.force_login(self.superuser)

    def _post_data(self, session):
        from core.models import SessionSubproject

        link = SessionSubproject.objects.get(session=session)
        local_start = timezone.localtime(session.start_time)
        local_end = timezone.localtime(session.end_time)
        return {
            "user": session.user_id,
            "project": session.project_id,
            "start_time_0": local_start.strftime("%Y-%m-%d"),
            "start_time_1": local_start.strftime("%H:%M:%S"),
            "end_time_0": local_end.strftime("%Y-%m-%d"),
            "end_time_1": local_end.strftime("%H:%M:%S"),
            "auto_stop_at_0": "",
            "auto_stop_at_1": "",
            "note": "posted-through-admin",
            "version": session.version,
            "subproject_links-TOTAL_FORMS": "1",
            "subproject_links-INITIAL_FORMS": "1",
            "subproject_links-MIN_NUM_FORMS": "0",
            "subproject_links-MAX_NUM_FORMS": "1000",
            "subproject_links-0-id": link.pk,
            "subproject_links-0-session": session.pk,
            "subproject_links-0-subproject": link.subproject_id,
            "subproject_links-0-allocation_bp": link.allocation_bp,
            "_save": "Save",
        }

    def test_admin_change_post_bumps_version_and_marks_commitment(self):
        session = self._make_session()
        version_before = session.version
        Commitment.objects.filter(pk=self.commitment.pk).update(needs_recompute=False)

        url = reverse("admin:core_sessions_change", args=[session.pk])
        response = self.client.post(url, self._post_data(session))

        # 302 => save succeeded (200 means the form re-rendered with errors).
        self.assertEqual(
            response.status_code,
            302,
            msg=getattr(
                getattr(response, "context_data", {}), "get", lambda *_: None
            )("errors"),
        )
        session.refresh_from_db()
        self.commitment.refresh_from_db()
        self.assertEqual(session.version, version_before + 1)
        self.assertTrue(self.commitment.needs_recompute)
