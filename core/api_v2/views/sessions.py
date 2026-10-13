from .base import *
class SessionsView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="sessions_list",
        parameters=[SessionListQuerySerializer],
        responses=SessionListResponseSerializer,
    )
    def get(self, request):
        pagination = SessionListQuerySerializer(
            data={
                key: request.query_params[key]
                for key in ("limit", "offset", "include", "ordering")
                if key in request.query_params
            }
        )
        pagination.is_valid(raise_exception=True)
        limit = pagination.validated_data["limit"]
        offset = pagination.validated_data["offset"]
        include_note = pagination.validated_data.get("include") == "note"

        spec = SessionFilterSpec.from_query_params(request.query_params, request.user)
        # The Sessions page's search (core.search.rank_sessions), so equivalent
        # requests return the same sessions in the same order.
        search = spec.rank(
            _session_queryset(request.user).filter(end_time__isnull=False),
            user=request.user,
            outcome=related_outcome(request),
        )
        if pagination.validated_data["ordering"] == "newest":
            queryset = search.combined().order_by(*SESSION_ORDER)
            total = queryset.count()
            related = set(search.related_ids)
            rows = [
                (session, RELATED if session.pk in related else DIRECT)
                for session in queryset[offset : offset + limit]
            ]
        else:
            total = search.total
            rows = search.page(offset, limit)
        sessions = []
        for session, match in rows:
            row = _serialize(session, include_note=include_note)
            if spec.search is not None:
                row["match"] = match
            sessions.append(row)
        return Response({"count": len(sessions), "total": total, "sessions": sessions})

    @extend_schema(
        request=SessionTrackRequestSerializer,
        responses={
            200: SessionResourceSerializer,
            201: SessionResourceSerializer,
        },
    )
    def post(self, request):
        serializer = SessionTrackRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = _resolve_project(request.user, data["project_id"])
        if "subproject_allocations" in data:
            allocations = _explicit_allocation_pairs(
                request.user, project, data["subproject_allocations"]
            )
            subprojects = [subproject for subproject, _ in allocations]
        else:
            subprojects = _resolve_subprojects(
                request.user, project, data.get("subproject_ids", [])
            )
            allocations = _even_allocation_pairs(subprojects)
        if data["end"] < data["start"]:
            raise ValidationError({"end": ["End must be on or after start."]})
        _validate_not_future(data["end"], "end")

        if "uuid" in data:
            existing = _session_queryset(request.user).filter(uuid=data["uuid"]).first()
            if existing is not None:
                if _canonical_existing(existing) == _canonical_track_payload(
                    project, allocations, data
                ):
                    return Response(_serialize(existing), status=status.HTTP_200_OK)
                return Response(
                    _envelope(
                        "uuid_conflict",
                        "The UUID is already assigned to different session content.",
                        {"current": _serialize(existing)},
                    ),
                    status=status.HTTP_409_CONFLICT,
                )

        fields = {
            "user": request.user,
            "project": project,
            "allocations": allocations,
            "start_time": data["start"],
            "end_time": data["end"],
            "is_active": False,
            "note": data.get("note"),
        }
        if "uuid" in data:
            fields["uuid"] = data["uuid"]
        session = SessionMutationService.create_session(**fields)
        return Response(_serialize(session), status=status.HTTP_201_CREATED)


class SessionDetailView(V2APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="sessions_retrieve", responses=SessionResourceSerializer)
    def get(self, request, session_id):
        return Response(_serialize(_get_session(request.user, session_id)))

    @extend_schema(
        request=SessionPatchRequestSerializer,
        parameters=[IF_MATCH_PARAMETER],
        responses={200: SessionResourceSerializer},
    )
    def patch(self, request, session_id):
        session = _get_session(request.user, session_id)
        expected_version = _parse_if_match(request)

        serializer = SessionPatchRequestSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = (
            _resolve_project(request.user, data["project_id"])
            if "project_id" in data
            else session.project
        )
        allocations = UNSET
        if "subproject_allocations" in data:
            allocations = _explicit_allocation_pairs(
                request.user, project, data["subproject_allocations"]
            )
        elif "subproject_ids" in data:
            subprojects = _resolve_subprojects(
                request.user, project, data["subproject_ids"]
            )
            allocations = _even_allocation_pairs(subprojects)
        elif "project_id" in data:
            _resolve_subprojects(
                request.user,
                project,
                [link.subproject_id for link in session.subproject_links.all()],
            )

        start_time = data.get("start", session.start_time)
        end_time = data.get("end", session.end_time)
        if end_time is not None and end_time < start_time:
            raise ValidationError({"end": ["End must be on or after start."]})
        if end_time is not None:
            _validate_not_future(end_time, "end")
        history_unaffected = _commitment_history_unaffected(
            request.user,
            (session.start_time, session.end_time, start_time, end_time),
        )
        try:
            session = SessionMutationService.mutate_session(
                session.pk,
                user=request.user,
                project=project if "project_id" in data else UNSET,
                start_time=data["start"] if "start" in data else UNSET,
                end_time=data["end"] if "end" in data else UNSET,
                is_active=False if "end" in data else UNSET,
                auto_stop_at=None if "end" in data else UNSET,
                note=data["note"] if "note" in data else UNSET,
                allocations=allocations,
                expected_version=expected_version,
            )
        except StaleVersionError as exc:
            return _version_conflict(exc.current)
        payload = _serialize(session)
        if history_unaffected:
            payload["commitment_history_unaffected"] = True
        return Response(payload, status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        parameters=[IF_MATCH_PARAMETER],
        responses={
            200: CommitmentHistoryWarningSerializer,
            204: OpenApiResponse(description="Session deleted."),
        },
    )
    def delete(self, request, session_id):
        session = (
            _session_queryset(request.user)
            .filter(pk=session_id)
            .first()
        )
        if session is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        expected_version = _parse_if_match(request)
        history_unaffected = _commitment_history_unaffected(
            request.user, (session.start_time, session.end_time)
        )
        try:
            SessionMutationService.delete_session(
                session.pk, user=request.user, expected_version=expected_version
            )
        except StaleVersionError as exc:
            return _version_conflict(exc.current)
        if history_unaffected:
            return Response({"commitment_history_unaffected": True})
        return Response(status=status.HTTP_204_NO_CONTENT)


