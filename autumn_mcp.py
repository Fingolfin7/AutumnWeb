# autumn_mcp_server.py
import os
import requests
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Autumn MCP Server")

AUTUMN_API_BASE = os.getenv("AUTUMN_API_BASE", "http://localhost:8000")
AUTUMN_API_TOKEN = os.getenv("AUTUMN_API_TOKEN")
AUTUMN_API_TIMEOUT = float(os.getenv("AUTUMN_API_TIMEOUT", "20"))

TIME_UNIT_LABEL = os.getenv("AUTUMN_TIME_UNIT", "minutes")


def _headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Accept-Units": TIME_UNIT_LABEL,
        "X-Autumn-Client": "mcp",
    }
    if AUTUMN_API_TOKEN:
        headers["Authorization"] = f"Token {AUTUMN_API_TOKEN}"
    if extra:
        headers.update(extra)
    return headers


def autumn_request(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Any:
    url = f"{AUTUMN_API_BASE}{endpoint}"
    resp = requests.request(
        method=method,
        url=url,
        headers=_headers(),
        params=params,
        json=json,
        data=data,
        timeout=AUTUMN_API_TIMEOUT,
    )

    if not resp.content or resp.status_code == 204:
        return {"status": resp.status_code}
    return resp.json()


def _params_compact(compact: bool, extra: Optional[Dict[str, Any]] = None):
    params = dict(extra or {})
    if compact is False:
        params["compact"] = "false"
    return params


def _with_units(payload: Any, compact: bool) -> Any:
    if isinstance(payload, dict):
        tagged = dict(payload)
        tagged["unit"] = TIME_UNIT_LABEL
        return tagged
    return payload


@mcp.tool(
    description="Start a live timer for a project. "
    "Use this when the user begins working *now*."
)
def start(
    project: str,
    subprojects: Optional[List[str]] = None,
    compact: bool = True,
):
    """Start a new timer for a project.
        - Use when the user says they are starting work immediately.
        - If they mention subprojects, include them.
        - Do not add a note for a start session
        - Do NOT use this for past sessions (use `track` instead).
    """
    payload: Dict[str, Any] = {"project": project}
    if subprojects:
        payload["subprojects"] = subprojects
    res = autumn_request(
        "POST", "/api/timer/start/", json=payload, params=_params_compact(compact)
    )
    return _with_units(res, compact)


@mcp.tool(
    description="Stop a live timer for a project. "
    "Use this when the user finishes working on a project or takes a break."
)
def stop(
    note: Optional[str] = None,
    session_id: Optional[int] = None,
    project: Optional[str] = None,
    compact: bool = True,
):
    """
    Stop a live timer for a project.
    - Use when the user finishes working on a project or takes a break.
    - If they mention a note, include it.

    """
    payload: Dict[str, Any] = {}
    if note is not None:
        payload["note"] = note
    if session_id is not None:
        payload["session_id"] = session_id
    if project is not None:
        payload["project"] = project
    res = autumn_request(
        "POST", "/api/timer/stop/", json=payload, params=_params_compact(compact)
    )
    return _with_units(res, compact)


@mcp.tool(
    description="Get the status of the current timer. "
    "Use this to check if the user is currently tracking time for a project. It returns the elapsed time of an active session "
)
def status(
    session_id: Optional[int] = None,
    project: Optional[str] = None,
    compact: bool = True,
):
    params: Dict[str, Any] = {}
    if session_id is not None:
        params["session_id"] = session_id
    if project is not None:
        params["project"] = project
    params = _params_compact(compact, params)
    res = autumn_request("GET", "/api/timer/status/", params=params)
    return _with_units(res, compact)


@mcp.tool(
    description="Log a past work session with explicit start/end times or date. "
    "Use this when the user wants to record work that already happened."
    "Make sure to confirm the project name and any subproject names before calling this."
    "Include a note if the user provides one."
)
def track(
    project: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    subprojects: Optional[List[str]] = None,
    note: Optional[str] = None,
    compact: bool = True,
):
    """Track a past session.
        - Use when the user specifies a time range or date in the past.
        - Do NOT use this for starting a live timer (use `start` instead).
    """
    payload: Dict[str, Any] = {"project": project}
    if start and end:
        payload["start"] = start
        payload["end"] = end
    else:
        payload["date"] = date
        payload["start_time"] = start_time
        payload["end_time"] = end_time
    if subprojects:
        payload["subprojects"] = subprojects
    if note:
        payload["note"] = note
    res = autumn_request(
        "POST", "/api/track/", json=payload, params=_params_compact(compact)
    )
    return _with_units(res, compact)


@mcp.tool()
def delete_timer(session_id: Optional[int] = None):
    payload: Dict[str, Any] = {}
    if session_id is not None:
        payload["session_id"] = session_id
    return autumn_request("DELETE", "/api/timer/delete/", json=payload)


@mcp.tool()
def remove_timer(session_id: Optional[int] = None):
    return delete_timer(session_id=session_id)


@mcp.tool()
def restart(
    session_id: Optional[int] = None,
    project: Optional[str] = None,
    compact: bool = True,
):
    payload: Dict[str, Any] = {}
    if session_id is not None:
        payload["session_id"] = session_id
    if project is not None:
        payload["project"] = project
    res = autumn_request(
        "POST", "/api/timer/restart/", json=payload, params=_params_compact(compact)
    )
    return _with_units(res, compact)


@mcp.tool(
    description="List all projects in Autumn. "
    "Use this to get a list of all projects the user can track time for. "
    "You can filter by start and end date to get projects created within that range."
    "Projects are grouped by Active, Paused, and Completed."
)
def projects(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    compact: bool = True,
):
    params: Dict[str, Any] = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    params = _params_compact(compact, params)
    return autumn_request("GET", "/api/projects/grouped/", params=params)


@mcp.tool(
    description="List all the subprojects of a project. "
    "Use this to get the subprojects under a specific project. "
)
def subprojects(project: str, compact: bool = True):
    params = _params_compact(compact, {"project": project})
    return autumn_request("GET", "/api/subprojects/", params=params)


@mcp.tool(
    description="Get the time tallies for a project by the session durations found between start_date and end_date. "
)
def totals(
    project: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    compact: bool = True,
):
    params: Dict[str, Any] = {"project": project}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    params = _params_compact(compact, params)
    res = autumn_request("GET", "/api/totals/", params=params)
    return _with_units(res, compact)


@mcp.tool(
    description="Rename a project or subproject. "
    "Use this when the user wants to change the name of an existing project or subproject."
)
def rename(project: str, new_name: str, subproject: Optional[str] = None):
    """
      Rename a project or subproject.
      JSON:
        - Project: { "type": "project", "project": "Old", "new_name": "New" }
        - Subproject: {
            "type": "subproject",
            "project": "Parent",
            "subproject": "OldSub",
            "new_name": "NewSub"
          }
      """
    if subproject:
        payload = {
            "type": "subproject",
            "project": project,
            "subproject": subproject,
            "new_name": new_name,
        }
    else:
        payload = {"type": "project", "project": project, "new_name": new_name}
    return autumn_request("POST", "/api/rename/", json=payload)


@mcp.tool()
def delete_project(project: str):
    return autumn_request("DELETE", "/api/project/delete/", json={"project": project})


@mcp.tool(
    description="Show activity logs. Filter by any of: project, subproject, period (default 'week', also 'day', 'month' or 'all'),"
                " start_date, end_date, note (snippet). By default the compact value is set to true, this means sessions will not include session notes,"
    " if you want to include session notes set compact to false. Units: minutes."
)
def log(
    period: Optional[str] = "week",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    project: Optional[str] = None,
    subproject: Optional[str] = None,
    note: Optional[str] = None,
    compact: bool = True,
):
    """
    Show activity logs. Filter by any of: project, subproject, start_date,
    end_date, note (snippet). Units: minutes.

    Supports:
      - period=week|month|day|all
      - start_date?, end_date?
      - project or project_name
      - subproject
      - note_snippet
      - compact?
    Defaults to period=week if no start/end/period filters provided by client.

    """
    params: Dict[str, Any] = {}
    if start_date or end_date:
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
    elif period:
        params["period"] = period
    if project:
        params["project"] = project  # alias supported by API
    if subproject:
        params["subproject"] = subproject
    if note:
        params["note_snippet"] = note
    params = _params_compact(compact, params)
    res = autumn_request("GET", "/api/log/", params=params)
    return _with_units(res, compact)


@mcp.tool(
    description="Search for sessions by project, subproject, start_date, end_date, note. "
    "Use this to find specific sessions based on various criteria. Rather than listing all sessions."
)
def search_sessions(
    project: Optional[str] = None,
    subproject: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    note: Optional[str] = None,
    active: bool = False,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    order: Optional[str] = None,
    compact: bool = True,
):
    """
    Search sessions by any of: project, subproject, start_date, end_date, note.
    At least one of those is required. Units: minutes.
    """
    params: Dict[str, Any] = {}
    if project:
        params["project"] = project
    if subproject:
        params["subproject"] = subproject
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if note:
        params["note_snippet"] = note
    if active:
        params["active"] = "true"
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    if order:
        params["order"] = order
    params = _params_compact(compact, params)
    res = autumn_request("GET", "/api/sessions/search/", params=params)
    return _with_units(res, compact)


# Optional utility
@mcp.tool(
    description="Search for existing projects by name. "
    "Use this to confirm or resolve the correct project name "
    "before calling other tools that require a project argument."
)
def search_projects(search_term: str):
    """Search for projects by name.
    - Use this when the user provides a project name that may not exactly match.
    - Always call this first if you are unsure whether the project exists.
    - The result will give you the canonical project name to use in other calls.
    """
    return autumn_request(
        "GET", "/api/search_projects/", params={"search_term": search_term}
    )


if __name__ == "__main__":
    mcp.run()