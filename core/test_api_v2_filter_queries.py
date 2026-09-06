from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from core.api_v2.filters import SessionFilterSpec
from core.models import Context, Projects, SubProjects, Tag


class SessionFilterOwnershipQueryTests(TestCase):
    def test_all_seven_id_filters_use_only_four_ownership_queries(self):
        context = Context.objects.create(user=self.user, name="Work")
        tag = Tag.objects.create(user=self.user, name="Focus")
        params = QueryDict(
            f"project_ids={self.project.id}&exclude_project_ids={self.other_owned_project.id}"
            f"&subproject_ids={self.subproject.id}&exclude_subproject_ids={self.subproject.id}"
            f"&tag_ids={tag.id}&exclude_tag_ids={tag.id}&context_ids={context.id}"
        )
        with self.assertNumQueries(4):
            spec = SessionFilterSpec.from_query_params(params, self.user)
        self.assertEqual(spec.tag_ids, frozenset({tag.id}))
        self.assertEqual(spec.context_ids, frozenset({context.id}))

    def setUp(self):
        self.user = User.objects.create_user(
            username="filter-owner", email="filter-owner@example.com"
        )
        self.other_user = User.objects.create_user(
            username="other-owner", email="other-owner@example.com"
        )
        self.project = Projects.objects.create(user=self.user, name="Mine")
        self.other_owned_project = Projects.objects.create(
            user=self.user, name="Also mine"
        )
        self.other_project = Projects.objects.create(
            user=self.other_user, name="Not mine"
        )
        self.subproject = SubProjects.objects.create(
            user=self.user, parent_project=self.project, name="Mine subproject"
        )
        self.other_subproject = SubProjects.objects.create(
            user=self.other_user,
            parent_project=self.other_project,
            name="Not mine subproject",
        )

    def test_include_and_exclude_project_ids_share_one_ownership_query(self):
        params = QueryDict(
            f"project_ids={self.project.id}&exclude_project_ids={self.other_owned_project.id}"
        )

        with self.assertNumQueries(1):
            spec = SessionFilterSpec.from_query_params(params, self.user)

        self.assertEqual(spec.project_ids, frozenset({self.project.id}))
        self.assertEqual(
            spec.exclude_project_ids, frozenset({self.other_owned_project.id})
        )

    def test_valid_include_and_foreign_exclude_only_rejects_exclude(self):
        params = QueryDict(
            f"project_ids={self.project.id}&exclude_project_ids={self.other_project.id}"
        )

        with self.assertRaises(ValidationError) as caught:
            SessionFilterSpec.from_query_params(params, self.user)

        self.assertEqual(set(caught.exception.detail), {"exclude_project_ids"})
        self.assertEqual(
            caught.exception.detail["exclude_project_ids"],
            ["One or more IDs do not belong to this user."],
        )

    def test_cross_user_ids_keep_field_specific_validation_errors(self):
        params = QueryDict(
            "project_ids={}&exclude_project_ids={}&subproject_ids={}&"
            "exclude_subproject_ids={}".format(
                self.other_project.id,
                self.other_project.id,
                self.other_subproject.id,
                self.other_subproject.id,
            )
        )

        with self.assertRaises(ValidationError) as caught:
            SessionFilterSpec.from_query_params(params, self.user)

        self.assertEqual(
            set(caught.exception.detail),
            {
                "project_ids",
                "exclude_project_ids",
                "subproject_ids",
                "exclude_subproject_ids",
            },
        )
        for field_name in caught.exception.detail:
            self.assertEqual(
                caught.exception.detail[field_name],
                ["One or more IDs do not belong to this user."],
            )

        # Projects and subprojects are validated independently, one query per
        # model even when both include and exclude fields are supplied.
        with self.assertNumQueries(2):
            try:
                SessionFilterSpec.from_query_params(params, self.user)
            except ValidationError:
                pass
