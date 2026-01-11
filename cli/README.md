# Autumn CLI

Command-line interface for AutumnWeb - time tracking and project management from your terminal.

## Installation

### Using pip

```bash
cd cli
pip install -e .
```

Or from the AutumnWeb root directory:

```bash
pip install -e ./cli
```

### Using uv

```bash
cd cli
uv pip install -e .
```

Or from the AutumnWeb root directory:

```bash
uv pip install -e ./cli
```

## Getting Started

### 1. Get Your API Key

First, you need to obtain an API token from your AutumnWeb instance:

1. Log into your AutumnWeb account in a browser
2. Navigate to `/get-auth-token/` (e.g., `http://localhost:8000/get-auth-token/`)
3. Enter your username and password
4. Copy the returned token

Alternatively, you can create a token programmatically or through the Django admin.

### 2. Configure the CLI

Run the setup command to configure your API key and base URL:

```bash
autumn auth setup
```

You'll be prompted for:
- **API Key**: Your AutumnWeb API token (you can paste it in)
- **Base URL**: The base URL of your AutumnWeb instance (default: `http://localhost:8000`, you can paste it in)

You can also provide them as command-line options:
```bash
autumn auth setup --api-key "your-token-here" --base-url "http://localhost:8000"
```

The configuration is saved to `~/.autumn/config.yaml`.

You can also set these via environment variables:
- `AUTUMN_API_KEY`: Your API token
- `AUTUMN_API_BASE`: Base URL (e.g., `http://localhost:8000`)

Environment variables take precedence over the config file.

### 3. Verify Configuration

Test your configuration:

```bash
autumn auth verify
```

## Usage

### Timer Commands

Start a timer:
```bash
autumn start "My Project"
autumn start "My Project" --subprojects "Frontend" "Backend" --note "Working on API"
```

Check timer status:
```bash
autumn status
autumn status --project "My Project"
```

Stop a timer:
```bash
autumn stop
autumn stop --project "My Project" --note "Finished for today"
```

Restart a timer:
```bash
autumn restart
```

Delete a timer:
```bash
autumn delete --session-id 123
```

### Session Commands

View activity logs:
```bash
autumn log  # Default: last week
autumn log --period month
autumn log --period fortnight  # 2 weeks
autumn log --period "lunar cycle"  # ~29.5 days
autumn log --period quarter  # 3 months
autumn log --period year
autumn log --period all  # All time
autumn log --project "My Project" --start-date 2024-01-01
```

Search sessions:
```bash
autumn log search --project "My Project"
autumn log search --start-date 2024-01-01 --end-date 2024-01-31
autumn log search --note-snippet "meeting"
```

Track a completed session manually:
```bash
autumn track "My Project" --start "2024-01-15 09:00:00" --end "2024-01-15 11:30:00" --note "Morning work session"
```

### Project Commands

List projects:
```bash
autumn projects
autumn projects --status active
```

Create a project:
```bash
autumn new "New Project" --description "Project description"
```

### Chart Commands

All charts can be displayed interactively or saved to a file using the `--save` option.

The chart command accepts a `--type` option with the following types:
- `pie` (default) - Project/subproject time distribution
- `bar` - Horizontal bar chart of project/subproject totals
- `scatter` - Session durations over time
- `calendar` - GitHub contribution-style calendar heatmap
- `wordcloud` - Word cloud from session notes
- `heatmap` - Activity heatmap by day of week and hour

Examples:
```bash
# Pie chart (default)
autumn chart
autumn chart --project "My Project"  # Shows subprojects

# Bar chart
autumn chart --type bar
autumn chart --type bar --project "My Project"

# Scatter plot
autumn chart --type scatter
autumn chart --type scatter --project "My Project"

# Calendar (GitHub contribution style)
autumn chart --type calendar
autumn chart --type calendar --start-date 2024-01-01 --end-date 2024-01-31

# Wordcloud
autumn chart --type wordcloud
autumn chart --type wordcloud --project "My Project"

# Heatmap
autumn chart --type heatmap
autumn chart --type heatmap --project "My Project"

# Save to file
autumn chart --type pie --save chart.png
autumn chart --type bar --save totals.png
```

## Features

- ✅ **Timer Management**: Start, stop, restart, and manage timers
- ✅ **Session Logs**: View and search your time tracking sessions (includes session notes in the output)
- ✅ **Project Management**: List and create projects
- ✅ **Charts & Visualization**: Generate beautiful charts with matplotlib/seaborn
  - Pie charts
  - Bar charts
  - Scatter plots
  - Calendar heatmaps (GitHub contribution style)
  - Word clouds
  - Activity heatmaps
- ✅ **Bidirectional Sync**: Changes in CLI sync with web app and vice versa
- ✅ **Text Tables**: Clean, formatted output for logs and search results (with colored status highlights)

## Configuration

Configuration is stored in `~/.autumn/config.yaml`:

```yaml
api_key: your_api_token_here
base_url: http://localhost:8000
```

You can also use environment variables:
- `AUTUMN_API_KEY`: Your API token
- `AUTUMN_API_BASE`: Base URL

## API Endpoints

The CLI communicates with your AutumnWeb instance using the REST API. All endpoints require authentication via the `Authorization: Token <api_key>` header.

Key endpoints used:
- `/api/timer/*` - Timer management
- `/api/log/` - Activity logs
- `/api/sessions/search/` - Session search
- `/api/track/` - Manual session tracking
- `/api/projects/grouped/` - Project listings
- `/api/tally_by_sessons/` - Project totals (for charts)
- `/api/tally_by_subprojects/` - Subproject totals (for charts)
- `/api/list_sessions/` - Session lists (for charts)

## Requirements

- Python 3.8+
- AutumnWeb instance running and accessible
- Valid API token from your AutumnWeb account

## Troubleshooting

### Authentication Errors

If you get authentication errors:
1. Verify your API key: `autumn auth status`
2. Check that your API key is valid in the web app
3. Ensure the base URL is correct and accessible

### Connection Errors

If you can't connect:
1. Verify the base URL is correct
2. Check that your AutumnWeb instance is running
3. Ensure there are no firewall/network issues

### Chart Display Issues

If charts don't display:
- Make sure you have a display available (X11 on Linux, or running in a GUI environment)
- Use `--save` to save charts to files instead
- Check that matplotlib backend is configured correctly for your system

### Wordcloud Chart

The wordcloud chart requires the `wordcloud` library. If you get an error, install it:
```bash
pip install wordcloud
```

## Development

To develop or modify the CLI:

```bash
cd cli
pip install -e ".[dev]"  # If you add dev dependencies
```

Run tests (when implemented):
```bash
pytest tests/
```

## License

Same as AutumnWeb project.
