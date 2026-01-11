"""Text formatting utilities for CLI output."""

from datetime import datetime, timedelta
from typing import List, Dict, Any

from rich.table import Table

from .console import console


def format_duration_minutes(minutes: float) -> str:
    """Format duration in minutes to human-readable string."""
    if minutes is None:
        return "N/A"

    hours = int(minutes // 60)
    mins = int(minutes % 60)

    if hours > 0:
        return f"{hours}h {mins}m"
    else:
        return f"{mins}m"


def format_duration_hours(hours: float) -> str:
    """Format duration in hours to human-readable string."""
    if hours is None:
        return "N/A"

    return f"{hours:.2f}h"


def format_datetime(iso_string: str) -> str:
    """Format ISO datetime string to readable format.

    Old-CLI-inspired: shorter and easier to scan.
    """
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y %H:%M")
    except Exception:
        return iso_string


def format_date(iso_string: str) -> str:
    """Format ISO date/datetime string to date only."""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso_string


def format_time_hms(iso_string: str) -> str:
    """Format an ISO datetime string to time-only (HH:MM:SS)."""
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return iso_string


def format_log_date_header(iso_date_or_datetime: str) -> str:
    """Format a date key (YYYY-MM-DD) to 'Weekday DD Month YYYY'."""
    try:
        # Accept either YYYY-MM-DD or a full ISO datetime
        part = iso_date_or_datetime.split("T", 1)[0]
        dt = datetime.fromisoformat(part)
        return dt.strftime("%A %d %B %Y")
    except Exception:
        return iso_date_or_datetime


def format_day_total_minutes(total_minutes: float) -> str:
    """Format a day total in minutes the old way (Xh Ym or Xm Ss-like).

    Mirrors old CLI behavior: if hours > 0 show 'Hh Mm', else show 'Mm Ss'.
    """
    try:
        td = timedelta(minutes=float(total_minutes or 0))
    except Exception:
        td = timedelta(minutes=0)

    seconds = int(td.total_seconds())
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)

    if hours > 0:
        return f"{hours:02d}h {minutes:02d}m"
    return f"{minutes:02d}m {secs:02d}s"


def _get_session_fields(session: Dict) -> Dict[str, Any]:
    """Normalize session dict keys from various API responses."""
    project = session.get("p") or session.get("project") or ""
    subs = session.get("subs") or session.get("subprojects") or []

    start_raw = session.get("start") or session.get("start_time") or ""
    end_raw = session.get("end") or session.get("end_time")

    duration = (
        session.get("dur")
        or session.get("duration_minutes")
        or session.get("elapsed_minutes")
        or session.get("elapsed")
        or 0
    )

    note = session.get("note") or ""

    return {
        "id": session.get("id"),
        "project": project,
        "subprojects": subs,
        "start": start_raw,
        "end": end_raw,
        "duration": duration,
        "note": note,
    }


def sessions_table(
    sessions: List[Dict],
    *,
    show_notes: bool = True,
    note_width: int = 40,
) -> Table:
    """Create a Rich table for sessions.

    Note: we return a Table so commands can print it with consistent styling.
    """
    table = Table(show_header=True, header_style="autumn.title", show_lines=False)

    table.add_column("ID", style="autumn.id", no_wrap=True)
    table.add_column("Project", style="autumn.project")
    table.add_column("Subprojects", style="autumn.subproject")
    table.add_column("Start", style="autumn.time", no_wrap=True)
    table.add_column("End", style="autumn.time", no_wrap=True)
    table.add_column("Dur", style="autumn.time", no_wrap=True, justify="right")
    if show_notes:
        table.add_column("Note", style="autumn.note", overflow="fold", max_width=note_width)

    if not sessions:
        table.add_row("-", "-", "-", "-", "-", "-", "No sessions found." if show_notes else "")
        return table

    for s in sessions:
        f = _get_session_fields(s)
        subs_str = ", ".join(f["subprojects"]) if f["subprojects"] else "-"

        start_str = format_datetime(f["start"])
        end_str = format_datetime(f["end"]) if f["end"] else "Active"
        dur_str = format_duration_minutes(float(f["duration"]) if f["duration"] is not None else 0)

        row = [
            str(f["id"] or ""),
            f["project"],
            subs_str,
            start_str,
            end_str,
            dur_str,
        ]
        if show_notes:
            note = f["note"].strip().replace("\r", " ").replace("\n", " ")
            row.append(note)

        # Highlight active sessions
        style = "autumn.ok" if not f["end"] else None
        table.add_row(*row, style=style)

    return table


def format_sessions_table(sessions: List[Dict], compact: bool = True) -> str:
    """Backwards-compatible wrapper.

    Older commands called this and expected a string; now we render a Rich table.
    Always includes notes in compact mode (per request).
    """
    table = sessions_table(sessions, show_notes=True)
    with console.capture() as capture:
        console.print(table)
    return capture.get()


def format_projects_table(projects_data: Dict) -> str:
    """Format projects grouped data as a table."""
    # Keep existing tabulate formatting for now (projects output change wasn't requested).
    from tabulate import tabulate

    projects = projects_data.get("projects", {})

    if not any(projects.values()):
        return "No projects found."

    headers = ["Status", "Projects"]
    rows = []

    for status in ["active", "paused", "complete"]:
        proj_list = projects.get(status, [])
        if isinstance(proj_list[0], str) if proj_list else False:
            # Compact format
            proj_str = ", ".join(proj_list) if proj_list else "-"
            rows.append([status.capitalize(), proj_str])
        else:
            # Full format
            proj_names = [p.get("name", "") for p in proj_list]
            proj_str = ", ".join(proj_names) if proj_names else "-"
            rows.append([status.capitalize(), proj_str])

    return tabulate(rows, headers=headers, tablefmt="grid")


def format_totals_table(totals_data: Dict) -> str:
    """Format project/subproject totals as a table."""
    from tabulate import tabulate

    project = totals_data.get("project", "")
    total = totals_data.get("total") or totals_data.get("total_minutes", 0)
    subs = totals_data.get("subs") or totals_data.get("subprojects", [])

    headers = ["Project/Subproject", "Total Time"]
    rows = [[project, format_duration_minutes(total)]]

    for sub in subs:
        if isinstance(sub, list):
            name, minutes = sub
        else:
            name = sub.get("name", "")
            minutes = sub.get("total_minutes", 0)
        rows.append([f"  └─ {name}", format_duration_minutes(minutes)])

    return tabulate(rows, headers=headers, tablefmt="grid")
