"""Main CLI entry point for Autumn CLI."""

import click
import requests
from .config import get_api_key, get_base_url, set_api_key, set_base_url, load_config
from .api_client import APIClient, APIError
from .commands.timer import start, stop, restart, delete, status as timer_status
from .commands.sessions import log, track
from .commands.projects import projects_list, new_project
from .commands.charts import chart


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Autumn CLI - Command-line interface for AutumnWeb."""
    pass


@cli.group()
def auth():
    """Authentication and configuration commands."""
    pass


@auth.command()
@click.option("--api-key", help="Your AutumnWeb API token (can also paste when prompted)")
@click.option("--base-url", help="AutumnWeb base URL (can also paste when prompted)")
def setup(api_key: str, base_url: str):
    """Configure API key and base URL."""
    # If not provided as arguments, prompt for them (hide_input=False allows pasting)
    if not api_key:
        api_key = click.prompt("API Key", hide_input=False)
    if not base_url:
        base_url = click.prompt("Base URL", default="http://localhost:8000")
    
    set_api_key(api_key)
    set_base_url(base_url)
    click.echo("Configuration saved successfully!")
    click.echo(f"Base URL: {base_url}")
    click.echo("API key saved (hidden)")
    
    # Verify the configuration
    try:
        verify()
    except:
        click.echo("\nWarning: Could not verify API key. Please check your credentials.")


@auth.command()
def verify():
    """Verify API key and connection."""
    try:
        api_key = get_api_key()
        base_url = get_base_url()
        
        if not api_key:
            click.echo("Error: API key not configured. Run 'autumn auth setup' first.", err=True)
            raise click.Abort()
        
        # Try to verify by making a simple API call
        client = APIClient()
        result = client.get_timer_status()
        
        click.echo("✓ Authentication successful!")
        click.echo(f"  Base URL: {base_url}")
        click.echo(f"  API key: {api_key[:8]}...")
    except APIError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@auth.command()
def status():
    """Show current configuration status."""
    config = load_config()
    api_key = get_api_key()
    base_url = get_base_url()
    
    click.echo("Configuration:")
    click.echo(f"  Base URL: {base_url}")
    if api_key:
        click.echo(f"  API key: {api_key[:8]}... (configured)")
    else:
        click.echo("  API key: Not configured")
    
    # Test connection
    if api_key:
        try:
            client = APIClient()
            client.get_timer_status()
            click.echo("  Connection: ✓ Working")
        except:
            click.echo("  Connection: ✗ Failed")


# Register commands directly (flat structure)
# Timer commands
cli.add_command(start, name="start")
cli.add_command(stop, name="stop")
cli.add_command(timer_status, name="status")  # Timer status
cli.add_command(restart, name="restart")
cli.add_command(delete, name="delete")

# Session commands
cli.add_command(log, name="log")
cli.add_command(track, name="track")

# Project commands
cli.add_command(projects_list, name="projects")
cli.add_command(new_project, name="new")

# Chart command
cli.add_command(chart, name="chart")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
