"""Session commands for Autumn CLI."""

import click
from typing import Optional
from datetime import datetime, timedelta, date

from ..api_client import APIClient, APIError
from ..utils.console import console
from ..utils.log_render import render_sessions_list


@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    "--period",
    "-p",
    type=click.Choice(
        ["day", "week", "fortnight", "month", "lunar cycle", "quarter", "year", "all"],
        case_sensitive=False,
    ),
    default="week",
    help="Time period (default: week)",
)
@click.option("--project", help="Filter by project name")
@click.option("--start-date", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
def log(
    ctx: click.Context,
    period: Optional[str],
    project: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
):
    """Show activity logs (saved sessions). Use 'log search' for advanced search."""
    # If a subcommand was invoked, don't run this command
    if ctx.invoked_subcommand is None:
        try:
            client = APIClient()

            normalized_period = period.lower() if period else "week"
            calculated_start_date = start_date
            calculated_end_date = end_date

            if not start_date and not end_date and normalized_period not in (
                "day",
                "week",
                "month",
                "all",
            ):
                today = date.today()
                if normalized_period == "fortnight":
                    calculated_start_date = (today - timedelta(days=14)).strftime("%Y-%m-%d")
                elif normalized_period == "lunar cycle":
                    calculated_start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
                elif normalized_period == "quarter":
                    quarter_start_month = ((today.month - 1) // 3) * 3 + 1
                    calculated_start_date = today.replace(month=quarter_start_month, day=1).strftime(
                        "%Y-%m-%d"
                    )
                elif normalized_period == "year":
                    calculated_start_date = today.replace(month=1, day=1).strftime("%Y-%m-%d")

                result = client.log_activity(
                    period=None,
                    project=project,
                    start_date=calculated_start_date,
                    end_date=calculated_end_date,
                )
            else:
                result = client.log_activity(
                    period=period,
                    project=project,
                    start_date=start_date,
                    end_date=end_date,
                )

            logs = result.get("logs", [])
            count = result.get("count", len(logs))

            console.print(f"[autumn.label]Sessions:[/] {count}")
            console.print(render_sessions_list(logs))
        except APIError as e:
            console.print(f"[autumn.err]Error:[/] {e}")
            raise click.Abort()


@log.command("search")
@click.option("--project", help="Filter by project name")
@click.option("--start-date", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
@click.option("--note-snippet", help="Search for text in notes")
@click.option("--active/--no-active", default=False, help="Include active sessions")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--offset", type=int, help="Offset for pagination")
def log_search(
    project: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    note_snippet: Optional[str],
    active: bool,
    limit: Optional[int],
    offset: Optional[int],
):
    """Search sessions with filters."""
    try:
        client = APIClient()
        result = client.search_sessions(
            project=project,
            start_date=start_date,
            end_date=end_date,
            note_snippet=note_snippet,
            active=active,
            limit=limit,
            offset=offset,
        )

        sessions_list = result.get("sessions", [])
        count = result.get("count", len(sessions_list))

        console.print(f"[autumn.label]Sessions:[/] {count}")
        console.print(render_sessions_list(sessions_list))
    except APIError as e:
        console.print(f"[autumn.err]Error:[/] {e}")
        raise click.Abort()


@click.command()
@click.argument("project")
@click.option("--subprojects", "-s", multiple=True, help="Subproject names (can specify multiple)")
@click.option(
    "--start",
    required=True,
    help="Start time (ISO format: YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD HH:MM:SS)",
)
@click.option(
    "--end",
    required=True,
    help="End time (ISO format: YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD HH:MM:SS)",
)
@click.option("--note", "-n", help="Note for the session")
def track(project: str, subprojects: tuple, start: str, end: str, note: Optional[str]):
    """Track a completed session (manually log time)."""
    try:
        start_iso = _normalize_datetime(start)
        end_iso = _normalize_datetime(end)

        client = APIClient()
        subprojects_list = list(subprojects) if subprojects else None
        result = client.track_session(project, start_iso, end_iso, subprojects_list, note)

        if result.get("ok"):
            session = result.get("session", {})
            duration = session.get("elapsed") or session.get("duration_minutes", 0)
            console.print("[autumn.ok]Session tracked.[/]")
            console.print(f"[autumn.label]ID:[/] {session.get('id')}")
            console.print(f"[autumn.label]Project:[/] {project}")
            console.print(f"[autumn.label]Duration:[/] {duration} minutes")
        else:
            console.print(f"[autumn.err]Error:[/] {result.get('error', 'Unknown error')}")
    except APIError as e:
        console.print(f"[autumn.err]Error:[/] {e}")
        raise click.Abort()
    except ValueError as e:
        console.print(f"[autumn.err]Error:[/] Invalid date format - {e}")
        raise click.Abort()


def _normalize_datetime(dt_str: str) -> str:
    """Normalize datetime string to ISO format."""
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.isoformat()
        except ValueError:
            continue

    if "T" in dt_str or ":" in dt_str:
        return dt_str

    raise ValueError(f"Could not parse datetime: {dt_str}")
