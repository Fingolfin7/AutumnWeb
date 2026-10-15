from .base import *
from django.db.models import F

from core.celebrations import is_completion_transition
from core.services.celebrations import project_completion_celebration


PROJECT_IF_MATCH_PARAMETER = OpenApiParameter(
    name="If-Match",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.HEADER,
    required=False,
    description="Optional current integer project version.",
)
SUBPROJECT_IF_MATCH_PARAMETER = OpenApiParameter(
    name="If-Match",
    type=OpenApiTypes.INT,
    location=OpenApiParameter.HEADER,
    required=False,
    description="Optional current integer subproject version.",
)


def _project_version_conflict(project):
    return Response(
        _envelope(
            "version_conflict",
            "The project has changed since the supplied version.",
            {"current": ProjectResourceSerializer(project).data},
        ),
        status=status.HTTP_409_CONFLICT,
    )


def _subproject_version_conflict(subproject):
    return Response(
        _envelope(
            "version_conflict",
            "The subproject has changed since the supplied version.",
            {"current": SubprojectResourceSerializer(subproject).data},
        ),
        status=status.HTTP_409_CONFLICT,
    )


class ProjectsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_list",
        parameters=[ProjectListQuerySerializer],
        responses=ProjectListResponseSerializer,
    )
    def get(self, request):
        serializer = ProjectListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        context_ids = _parse_owned_filter_ids(
            request.query_params.get("context_ids"),
            field_name="context_ids",
            model=Context,
            user=request.user,
        )
        tag_ids = _parse_owned_filter_ids(
            request.query_params.get("tag_ids"),
            field_name="tag_ids",
            model=Tag,
            user=request.user,
        )
        excluded_ids = _parse_owned_filter_ids(
            request.query_params.get("exclude_project_ids"),
            field_name="exclude_project_ids",
            model=Projects,
            user=request.user,
        )

        queryset = _project_queryset(request.user)
        if "status" in data:
            queryset = queryset.filter(status=data["status"])
        if context_ids is not None:
            queryset = queryset.filter(context_id__in=context_ids)
        if tag_ids is not None:
            queryset = queryset.filter(tags__id__in=tag_ids).distinct()
        if excluded_ids is not None:
            queryset = queryset.exclude(pk__in=excluded_ids)
        # Last: related matches are drawn from what the other filters left.
        if data.get("search"):
            matches = queryset.filter(
                Q(name__icontains=data["search"])
                | Q(description__icontains=data["search"])
                | Q(subprojects__name__icontains=data["search"])
            ).distinct()
            if data.get("related"):
                matches = with_extra(
                    queryset,
                    matches,
                    related_project_ids(
                        request.user,
                        queryset,
                        matches,
                        data["search"],
                        limit=None,
                        outcome=related_outcome(request),
                    ),
                )
            queryset = matches
        current_timezone = timezone.get_current_timezone()
        if data.get("start_date") is not None:
            start = timezone.make_aware(
                datetime.combine(data["start_date"], time.min),
                current_timezone,
            )
            queryset = queryset.filter(start_date__gte=start)
        if data.get("end_date") is not None:
            end = timezone.make_aware(
                datetime.combine(data["end_date"] + timedelta(days=1), time.min),
                current_timezone,
            )
            queryset = queryset.filter(start_date__lt=end)
        ordering = data["ordering"]
        if ordering == "name":
            queryset = queryset.order_by("name", "id")
        elif ordering == "last_activity":
            queryset = queryset.order_by("-derived_last_updated", "id")
        else:
            queryset = queryset.order_by("id")

        total = queryset.count()
        offset = data["offset"]
        projects = list(queryset[offset : offset + data["limit"]])
        return Response(
            {
                "count": len(projects),
                "total": total,
                "projects": ProjectResourceSerializer(projects, many=True).data,
            }
        )

    @extend_schema(
        operation_id="projects_create",
        request=ProjectCreateRequestSerializer,
        responses={201: ProjectResourceSerializer},
    )
    def post(self, request):
        serializer = ProjectCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if Projects.objects.filter(user=request.user, name=data["name"]).exists():
            return _conflict(DestructiveOperationError("Project name already exists"))
        context = (
            _resolve_context(request.user, data["context_id"])
            if "context_id" in data
            else None
        )
        tags = (
            _resolve_tags(request.user, data["tag_ids"])
            if "tag_ids" in data
            else []
        )
        with transaction.atomic():
            project = Projects.objects.create(
                user=request.user,
                name=data["name"],
                description=data.get("description", ""),
                status=data["status"],
                context=context,
            )
            if "context_id" in data and context is None:
                Projects.objects.filter(pk=project.pk).update(context=None)
            if "tag_ids" in data:
                project.tags.set(tags)
        project = _get_project(request.user, project.pk)
        return Response(
            ProjectResourceSerializer(project).data,
            status=status.HTTP_201_CREATED,
        )


class ProjectDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_retrieve",
        responses=ProjectDetailResourceSerializer,
    )
    def get(self, request, project_id):
        project = _get_project(
            request.user, project_id, include_subprojects=True
        )
        return Response(ProjectDetailResourceSerializer(project).data)

    @extend_schema(
        operation_id="projects_partial_update",
        request=ProjectPatchRequestSerializer,
        parameters=[PROJECT_IF_MATCH_PARAMETER],
        responses={200: ProjectResourceSerializer},
    )
    def patch(self, request, project_id):
        expected_version = _parse_if_match(request)
        serializer = ProjectPatchRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = (
            _resolve_context(request.user, data["context_id"])
            if "context_id" in data
            else None
        )
        tags = (
            _resolve_tags(request.user, data["tag_ids"])
            if "tag_ids" in data
            else None
        )
        try:
            with transaction.atomic():
                try:
                    locked = Projects.objects.select_for_update().get(
                        user=request.user, pk=project_id
                    )
                except Projects.DoesNotExist as exc:
                    raise NotFound(f"Project {project_id} not found.") from exc
                if expected_version is not None and expected_version != locked.version:
                    return _project_version_conflict(
                        _get_project(request.user, project_id)
                    )
                previous_status = locked.status
                project = locked
                if "name" in data:
                    project = DestructiveMutationService.rename_project(
                        user=request.user,
                        project_name=project.name,
                        new_name=data["name"],
                    )
                updates = {}
                if "description" in data:
                    updates["description"] = data["description"]
                if "status" in data:
                    updates["status"] = data["status"]
                if "context_id" in data:
                    updates["context_id"] = context.pk if context else None
                if "start_date" in data:
                    updates["start_date"] = _as_start_datetime(data["start_date"])
                if updates:
                    Projects.objects.filter(pk=project.pk).update(**updates)
                if "description" in updates:
                    # update() bypasses post_save; the description is
                    # part of the project's search text.
                    request_sync_on_commit(request.user.pk)
                if tags is not None:
                    project.tags.set(tags)
                if data:
                    Projects.objects.filter(pk=project.pk).update(
                        version=F("version") + 1
                    )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        project = _get_project(request.user, project.pk)
        if is_completion_transition(previous_status, project.status):
            project.celebration = project_completion_celebration(request.user, project)
        return Response(ProjectResourceSerializer(project).data)

    @extend_schema(
        operation_id="projects_destroy",
        request=None,
        parameters=[PROJECT_IF_MATCH_PARAMETER],
        responses={204: OpenApiResponse(description="Project deleted.")},
    )
    def delete(self, request, project_id):
        with transaction.atomic():
            project = (
                Projects.objects.select_for_update()
                .filter(user=request.user, pk=project_id)
                .first()
            )
            if project is None:
                if Projects.objects.filter(pk=project_id).exists():
                    raise NotFound(f"Project {project_id} not found.")
                return Response(status=status.HTTP_204_NO_CONTENT)
            expected_version = _parse_if_match(request)
            if expected_version is not None and expected_version != project.version:
                return _project_version_conflict(
                    _get_project(request.user, project_id)
                )
            try:
                DestructiveMutationService.delete_project(
                    user=request.user, project_name=project.name
                )
            except DestructiveOperationError as exc:
                return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectMergeView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="projects_merge",
        request=ProjectMergeRequestSerializer,
        responses={201: ProjectResourceSerializer},
    )
    def post(self, request):
        serializer = ProjectMergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sources = [
            _resolve_project(request.user, project_id)
            for project_id in data["source_ids"]
        ]
        try:
            merged, _ = DestructiveMutationService.merge_projects(
                user=request.user,
                project1_name=sources[0].name,
                project2_name=sources[1].name,
                new_project_name=data["new_name"],
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        merged = _get_project(request.user, merged.pk)
        return Response(
            ProjectResourceSerializer(merged).data,
            status=status.HTTP_201_CREATED,
        )


class ProjectSubprojectsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_subprojects_list",
        responses=SubprojectListResponseSerializer,
    )
    def get(self, request, project_id):
        project = _resolve_project(request.user, project_id)
        subprojects = list(
            _subproject_queryset(request.user)
            .filter(parent_project=project)
            .order_by("name", "id")
        )
        return Response(
            {
                "count": len(subprojects),
                "subprojects": SubprojectResourceSerializer(
                    subprojects, many=True
                ).data,
            }
        )

    @extend_schema(
        operation_id="project_subprojects_create",
        request=SubprojectCreateRequestSerializer,
        responses={201: SubprojectResourceSerializer},
    )
    def post(self, request, project_id):
        project = _resolve_project(request.user, project_id)
        serializer = SubprojectCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if SubProjects.objects.filter(
            user=request.user, parent_project=project, name=data["name"]
        ).exists():
            return _conflict(
                DestructiveOperationError("Subproject name already exists")
            )
        subproject = SubProjects.objects.create(
            user=request.user,
            parent_project=project,
            name=data["name"],
            description=data.get("description", ""),
            **(
                {"start_date": _as_start_datetime(data["start_date"])}
                if "start_date" in data
                else {}
            ),
        )
        subproject = _get_subproject(request.user, subproject.pk)
        return Response(
            SubprojectResourceSerializer(subproject).data,
            status=status.HTTP_201_CREATED,
        )


class SubprojectDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="subprojects_retrieve",
        responses=SubprojectResourceSerializer,
    )
    def get(self, request, subproject_id):
        return Response(
            SubprojectResourceSerializer(
                _get_subproject(request.user, subproject_id)
            ).data
        )

    @extend_schema(
        operation_id="subprojects_partial_update",
        request=SubprojectPatchRequestSerializer,
        parameters=[SUBPROJECT_IF_MATCH_PARAMETER],
        responses={200: SubprojectResourceSerializer},
    )
    def patch(self, request, subproject_id):
        expected_version = _parse_if_match(request)
        serializer = SubprojectPatchRequestSerializer(
            data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                try:
                    subproject = SubProjects.objects.select_for_update().get(
                        user=request.user, pk=subproject_id
                    )
                except SubProjects.DoesNotExist as exc:
                    raise NotFound(
                        f"Subproject {subproject_id} not found."
                    ) from exc
                if (
                    expected_version is not None
                    and expected_version != subproject.version
                ):
                    return _subproject_version_conflict(
                        _get_subproject(request.user, subproject_id)
                    )
                if "name" in data:
                    subproject = DestructiveMutationService.rename_subproject(
                        user=request.user,
                        project_name=subproject.parent_project.name,
                        subproject_name=subproject.name,
                        new_name=data["name"],
                    )
                updates = {}
                if "description" in data:
                    updates["description"] = data["description"]
                if "start_date" in data:
                    updates["start_date"] = _as_start_datetime(data["start_date"])
                if data:
                    updates["version"] = F("version") + 1
                if updates:
                    SubProjects.objects.filter(pk=subproject.pk).update(**updates)
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(
            SubprojectResourceSerializer(
                _get_subproject(request.user, subproject.pk)
            ).data
        )

    @extend_schema(
        operation_id="subprojects_destroy",
        request=None,
        parameters=[SUBPROJECT_IF_MATCH_PARAMETER],
        responses={204: OpenApiResponse(description="Subproject deleted.")},
    )
    def delete(self, request, subproject_id):
        with transaction.atomic():
            subproject = (
                SubProjects.objects.select_for_update()
                .select_related("parent_project")
                .filter(user=request.user, pk=subproject_id)
                .first()
            )
            if subproject is None:
                if SubProjects.objects.filter(pk=subproject_id).exists():
                    raise NotFound(f"Subproject {subproject_id} not found.")
                return Response(status=status.HTTP_204_NO_CONTENT)
            expected_version = _parse_if_match(request)
            if (
                expected_version is not None
                and expected_version != subproject.version
            ):
                return _subproject_version_conflict(
                    _get_subproject(request.user, subproject_id)
                )
            try:
                DestructiveMutationService.delete_subproject(
                    user=request.user,
                    project_name=subproject.parent_project.name,
                    subproject_name=subproject.name,
                )
            except DestructiveOperationError as exc:
                return _conflict(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubprojectMergeView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="subprojects_merge",
        request=SubprojectMergeRequestSerializer,
        responses={201: SubprojectResourceSerializer},
    )
    def post(self, request):
        serializer = SubprojectMergeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = _resolve_project(request.user, data["project_id"])
        sources = []
        for subproject_id in data["source_ids"]:
            try:
                sources.append(
                    SubProjects.objects.get(
                        user=request.user,
                        parent_project=project,
                        pk=subproject_id,
                    )
                )
            except SubProjects.DoesNotExist as exc:
                raise NotFound(
                    f"Subproject {subproject_id} not found."
                ) from exc
        try:
            merged = DestructiveMutationService.merge_subprojects(
                user=request.user,
                project_id=project.pk,
                name1=sources[0].name,
                name2=sources[1].name,
                new_name=data["new_name"],
            )
        except DestructiveOperationError as exc:
            return _conflict(exc)
        return Response(
            SubprojectResourceSerializer(
                _get_subproject(request.user, merged.pk)
            ).data,
            status=status.HTTP_201_CREATED,
        )

