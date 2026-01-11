"""Project commands for Autumn CLI."""

import click
from typing import Optional
from ..api_client import APIClient, APIError
from ..utils.formatters import format_projects_table


@click.command()
@click.option("--status", type=click.Choice(["active", "paused", "complete"]), help="Filter by status")
@click.option("--start-date", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
def projects_list(status: Optional[str], start_date: Optional[str], end_date: Optional[str]):
    """List projects grouped by status."""
    try:
        client = APIClient()
        result = client.list_projects_grouped(start_date, end_date)
        
        projects_data = result.get("projects", {})
        summary = result.get("summary", {})
        
        # Filter by status if requested
        if status:
            filtered_projects = {status: projects_data.get(status, [])}
            result["projects"] = filtered_projects
        
        click.echo(f"Total projects: {summary.get('total', 0)}")
        click.echo(f"  Active: {summary.get('active', 0)}")
        click.echo(f"  Paused: {summary.get('paused', 0)}")
        click.echo(f"  Complete: {summary.get('complete', 0)}\n")
        
        click.echo(format_projects_table(result))
    except APIError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@click.command()
@click.argument("project")
@click.option("--description", "-d", help="Project description")
def new_project(project: str, description: Optional[str]):
    """Create a new project."""
    try:
        client = APIClient()
        result = client.create_project(project, description)
        
        click.echo(f"Project created: {project}")
        if description:
            click.echo(f"  Description: {description}")
    except APIError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
