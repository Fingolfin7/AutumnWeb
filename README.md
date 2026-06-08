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
- **Password**: `autumnweb`

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
* Start, stop, restart, and remove timers directly in the browser
* Browse and search session history, including context, tag, date, note, and excluded-project filters
* Organize projects by hard **contexts** and soft **tags**
* Create time-based or session-based commitments with weekly/monthly/etc. targets and banking
* Visualize data with Chart.js charts, scatter plots, heatmaps, treemaps, and word clouds
* Export and import JSON data compatible with the old CLI version
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
python manage.py shell -c "exec(open('scripts/seed_finrod.py', 'r', encoding='utf-8').read())"
python manage.py runserver
```

Optional:

```bash
python manage.py createsuperuser  # For admin access
```

Access the app at `http://127.0.0.1:8000/`.

---

### Tech Stack

* **Backend**: Django, Django REST Framework, SQLite
* **Frontend**: HTML/CSS/JS (jQuery), Chart.js, wordcloud2.js
* **LLM**: Gemini, OpenAI/Codex login, OpenAI API key, and Claude integration paths
* **Import/Export**: JSON-based, compatible with Autumn CLI
* **No analytics or tracking**

---

### API Docs

See `docs/api.md` for a reference of `/api/*` endpoints used by the CLI wrapper and integrations.

---

Built with care. Use it if it is useful to you.
