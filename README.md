# Autumn

A minimalist, web-based time and project tracking tool.

**Autumn** is a Django application for tracking time across projects and subprojects, reviewing session history, managing commitments, and visualizing activity through charts, heatmaps, and word clouds. It also includes an optional LLM-powered **Insights** workspace for asking natural-language questions about your session data.

This project builds on the original [Autumn CLI](https://github.com/Fingolfin7/Autumn), offering a browser-accessible alternative with the same core structure and import/export compatibility.

---

### Try It

A demo is available here:
[https://autumn-lg0b.onrender.com/](https://autumn-lg0b.onrender.com/)

Use this demo account to explore the features:

- **Username**: `Finrod`
- or **Email**: `finrod.felagund@houseoffinwe.ea`
- **Password**: supplied privately by the instance owner

The instance runs on Render and may sleep between requests.

---

### Screenshots

**Home and Commitments**
![Home and Commitments](docs/screenshots/home.png)

**Session Logs**
![Session Logs](docs/screenshots/sessions.png)

**Timers**
![Timers](docs/screenshots/timers.png)

**Projects**
![Projects](docs/screenshots/projects.png)

**Contexts**
![Contexts](docs/screenshots/contexts.png)

**Tags**
![Tags](docs/screenshots/tags.png)

**Insights**
![Insights](docs/screenshots/insights.png)

**Import**
![Import](docs/screenshots/import.png)

**Export**
![Export](docs/screenshots/export.png)

**Profile**
![Profile](docs/screenshots/profile.png)

### Chart Tour

Autumn includes pie, bar, scatter, line, calendar, heatmap, stacked area, cumulative, treemap, status, context, histogram, radar, tag bubble, and word cloud charts.

![Chart Tour](docs/screenshots/chart-tour.gif)

---

### Features

* Track time spent on projects and subprojects
* Start, stop, restart, and remove timers directly in the browser, with optional server-side auto-stop deadlines
* Browse and search session history, including context, tag, date, note, and excluded-project filters
* Organize projects by hard **contexts** and soft **tags**
* Create time-based or session-based commitments with weekly/monthly/etc. targets and banking, in the browser or API
* Visualize data with Chart.js charts, scatter plots, heatmaps, treemaps, and word clouds
* Export and import JSON data compatible with the old CLI version, including JSON import through the API
* Ask natural-language questions about selected sessions with optional LLM integration
* Dark Night Ledger interface with optional custom, Bing, or NASA APOD workspace backgrounds

---

### Local Setup

To run the project locally:

```bash
git clone https://github.com/Fingolfin7/AutumnWeb.git
cd AutumnWeb
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
python manage.py migrate
# Set FINROD_PASSWORD in your shell before running the seed command.
python manage.py shell -c "exec(open('scripts/seed_finrod.py', 'r', encoding='utf-8').read())"
python manage.py runserver
```

Optional:

```bash
python manage.py createsuperuser  # For admin access
```

Access the app at `http://127.0.0.1:8000/`.

### Browser timer reminders

Browser reminders use Web Push and are optional. Configure the deployment with
the VAPID public key, private key, and a `mailto:` subject:

```text
PUSH_VAPID_PUBLIC_KEY=<base64url public key>
PUSH_VAPID_PRIVATE_KEY=<private key secret>
PUSH_VAPID_SUBJECT=mailto:admin@example.com
# Optional comma-separated additions/replacements for browser push providers:
PUSH_ALLOWED_ENDPOINT_SUFFIXES=fcm.googleapis.com,push.services.mozilla.com,notify.windows.com,push.apple.com
```

Generate a keypair with `python -m py_vapid --gen`. The public-key command
prints a labelled line; store only the value after `Application Server Key =`:

```powershell
$keyLine = python -m py_vapid --applicationServerKey --private-key .\private_key.pem |
    Where-Object { $_ -match '^Application Server Key = ' } |
    Select-Object -First 1
$env:PUSH_VAPID_PUBLIC_KEY = ($keyLine -replace '^Application Server Key =\s*', '').Trim()
$env:PUSH_VAPID_PRIVATE_KEY = (Resolve-Path .\private_key.pem).Path
$env:PUSH_VAPID_SUBJECT = 'mailto:admin@example.com'
```

On PaaS deployments that cannot ship a key file, set `PUSH_VAPID_PRIVATE_KEY` to
a base64url-encoded 32-byte P-256 private scalar. Do not paste raw PEM contents
including the `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----`
lines into the environment variable; use a mounted PEM file path instead.

Keep the private key server-only; the browser receives only the public key.
Subscription endpoints are restricted to the configured browser push-provider
host suffixes so the dispatcher cannot be aimed at arbitrary HTTPS services.
The timer-page test action queues a fixed notification for the dispatcher and
does not accept a provider endpoint or make a network request.

Delivery needs something to run the dispatch pass. There are two supported
modes; pick one.

**Cron (default).** Run `python manage.py dispatch_timer_reminders --once` from
cron. For local testing, use bounded `--loop --max-seconds 30` mode.

**In-process dispatcher thread (opt-in).** Set `RUN_REMINDER_DISPATCHER=TRUE`
and the web process starts a daemon thread that runs the same pass on a timer.
This suits local `runserver` and single-service Render deployments where no
cron or worker service is available:

```text
RUN_REMINDER_DISPATCHER=FALSE     # TRUE starts the dispatcher inside the web process
PUSH_DISPATCH_INTERVAL_SECONDS=15 # Seconds between passes when the thread runs
```

The thread only starts in a web process — `runserver` (in the autoreload child,
or with `--noreload`) and gunicorn/uvicorn/daphne. Management commands such as
`test`, `migrate`, `check`, and `dispatch_timer_reminders` itself never start
it. Both modes take the same best-effort cache lock, so a cron job and the
thread do not run a pass at the same time when they share a cache backend.
Note that on a free-tier service that sleeps when idle, nothing dispatches
while the service is asleep; reminders are delivered after it wakes.

---

### Tech Stack

* **Backend**: Django, Django REST Framework, SQLite
* **Frontend**: HTML/CSS/JS (jQuery), Chart.js, wordcloud2.js
* **LLM**: Gemini, OpenAI/Codex login, OpenAI API key, and Claude integration paths
* **Import/Export**: JSON-based, compatible with Autumn CLI
* **No analytics or tracking**

---

### API Docs

See `docs/api.md` for `/api/*` endpoints used by the CLI wrapper and integrations, including commitments, project metadata, context/tag management, and JSON import. `GET /healthz/` is an unauthenticated health check for waking or probing a sleeping deployment.

---

Built with care. Use it if it is useful to you.
