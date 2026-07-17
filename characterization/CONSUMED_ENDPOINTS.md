# Consumed v1 endpoint inventory

The CLI/MCP inventory supplied for the Autumn 2.0 work is authoritative. The
checked-in `autumn_mcp.py`, `core/urls.py`, chart template, and chart JavaScript
were cross-checked while building this table. `default` means no query params;
`full` means `compact=false`; `bounded` is the deterministic last-seven-days raw
range; `project` means the deterministic top projects from the clone. The semantic
suite additionally uses all-time plus absolute 7/30/365-day ranges, the top three
projects, two alphabetical contexts, and two alphabetical tags where available.

| Endpoint | Consumers | Raw golden coverage |
|---|---|---|
| `api/me/` | CLI, MCP | default |
| `api/timer/status/` | CLI, MCP | default, full |
| `api/log/` | CLI, MCP | default, full, bounded, project |
| `api/sessions/search/` | CLI, MCP | bounded/full, project/full |
| `api/list_sessions/` | CLI, MCP | default, bounded, project |
| `api/session/<id>/` | CLI, MCP | GET method contract (405); PATCH mutation chain |
| `api/projects/` | CLI, MCP | default, full |
| `api/projects/grouped/` | CLI, MCP | default/full, bounded, project |
| `api/projects_with_stats/` | CLI, MCP | default, bounded, project |
| `api/get_project/<project_name>/` | CLI, MCP | first top project |
| `api/search_projects/` | CLI, MCP | default |
| `api/list_projects/` | CLI | default, bounded |
| `api/subprojects/` | CLI, MCP | missing-project/default error, project, project/full |
| `api/list_subprojects/` | CLI | project |
| `api/search_subprojects/` | CLI, MCP | project |
| `api/contexts/` | CLI, MCP | list default/full |
| `api/contexts/<id>/` | CLI | first detail GET method contracts (405) |
| `api/tags/` | CLI, MCP | list default/full |
| `api/tags/<id>/` | CLI | first detail GET method contracts (405) |
| `api/commitments/`, `api/commitments/<id>/` | CLI | list default/full; first detail |
| `api/tally_by_sessions/` | CLI, MCP | default, bounded, top-three projects |
| `api/tally_by_subprojects/` | CLI, MCP | default, bounded, top-three projects |
| `api/tally_by_context/` | CLI, MCP | default, bounded, top-three project params |
| `api/tally_by_status/` | CLI, MCP | default, bounded, top-three project params |
| `api/tally_by_tags/` | CLI, MCP | default, bounded, top-three project params |
| `api/hierarchy/` | CLI, MCP | default, bounded, project |
| `api/totals/` | CLI, MCP | missing-project/default error/full, top-three projects/full |
| `api/export/` | CLI, MCP | default/full, bounded, top-three projects |
| `api/chart_data/` | web charts | scatter, line, stacked_area, calendar, cumulative, heatmap, histogram, wordcloud; each all-time, bounded, and first-project |
| `api/create_project/`, `api/create_subproject/`, `api/rename/`, `api/mark/`, `api/project/delete/` | CLI, MCP | fixed `CHZ ` project scenario chain |
| `api/project/update/` | CLI | fixed `CHZ ` project scenario chain |
| `api/timer/start/`, `api/timer/stop/`, `api/timer/restart/`, `api/timer/delete/`, `api/track/` | CLI, MCP | fixed frozen-time timer/session chains |
| `api/delete_session/<id>/`, `api/delete_subproject/<project>/<subproject>/` | CLI, MCP | fixed `CHZ ` delete chains |
| `api/merge_projects/`, `api/merge_subprojects/` | CLI, MCP | fixed `CHZ ` merge chains |
| `api/import/` | CLI | fixed import chain |
| `api/audit/` | CLI, MCP | fixed rolled-back audit chain |

## URL inventory discrepancies

- The supplied read inventory lists `api/session/<id>/`, but the exact route is
  `api/session/(?P<session_id>-?\d+)/` and its view accepts **PATCH only**. A raw
  GET golden records the current 405 contract; semantic coverage excludes it.
- `api/get_project/` is not a complete route: `core/urls.py` requires
  `api/get_project/<str:project_name>/`.
- `api/delete_session/` requires a signed-integer `<session_id>` path segment.
- `api/delete_subproject/` requires `<project_name>/<subproject_name>/` path
  segments. `api/subprojects/` is the separate query-parameter compact endpoint.
- Context, tag, and commitment details require integer IDs at
  `api/contexts/<id>/`, `api/tags/<id>/`, and `api/commitments/<id>/`.
- Despite being supplied as read details, the current context and tag detail
  views accept PATCH/DELETE only; raw GET goldens record 405 and the semantic
  suite excludes those non-read routes. Commitment detail does accept GET.
- `api/projects/grouped/` and `api/list_projects/` date-filtered variants used to
  500 with `ModuleNotFoundError: core.api.utils` (stale relative import in the
  `in_window` helper after the api package split). Fixed during S0
  (core/api/helpers.py + regression tests in core/test_api_projects_window.py);
  goldens were captured after the fix and lock the working responses.
- `core/urls.py` also exposes legacy/read compatibility endpoints used by the
  inventory (`api/list_projects/`, `api/list_subprojects/`) and the additional
  computed read `api/list_active_sessions/`; the semantic suite covers them.

## Nondeterminism found

None after two consecutive compare runs. `ENDPOINT_SORT_KEYS` therefore remains
empty and list order is preserved everywhere.
