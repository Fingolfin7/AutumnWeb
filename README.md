## 🍁 Autumn 

A minimalist, web-based time and project tracking tool.

**Autumn** is a Django application that lets you track how you spend your time across projects and subprojects, view your session history, and visualize your data through charts, heatmaps, and word clouds. It also includes an optional LLM-powered "Insights" feature, where you can ask questions about your session data using natural language.

This project builds on the original [Autumn CLI](https://github.com/Fingolfin7/Autumn), offering a browser-accessible alternative with the same core structure and import/export compatibility.
---

### Try It

A demo is available here:
👉 [http://fingolfin7.pythonanywhere.com/](http://fingolfin7.pythonanywhere.com/)

Use this demo account to explore the features:
- **Username**: `Finrod` 
- or **Email**: `finrod.felagund@houseoffinwe.ea`
- **Password**: `autumnweb`

The instance is running on a free PythonAnywhere account — load times may vary.

---

### Screenshots

**Projects Page (Dark mode + Bing wallpaper)**
![Projects](https://github.com/user-attachments/assets/ea91c1d7-4ed5-4891-ab57-36daa2fdde27)

**Projects Page (Dark mode, no background)**
![Projects](https://github.com/user-attachments/assets/9d0f9211-f7c8-4359-91c8-90de571d4c29)

**Projects Page (Light mode)**
![Projects](https://github.com/user-attachments/assets/a2c24c0f-ca49-447c-9072-83066797e766)

**Session History**
![Sessions](https://github.com/user-attachments/assets/f79a7097-0f2a-40d5-9190-a71b0bafe65e)

**Timers**
![Timers](https://github.com/user-attachments/assets/2933c467-15cd-4191-befa-5bea096229f3)

**Insights (LLM chat)**
![Insights](https://github.com/user-attachments/assets/a6ae39f0-e972-418a-9989-f3b62c2cd4dd)

**Charts and Heatmaps**
![Charts](https://github.com/user-attachments/assets/382046ca-7a65-46d9-851f-6185738ce2fb)
*Gif Made with [this](https://github.com/Fingolfin7/GIF-Maker)

**Profile Page and Background Settings**
![Profile](https://github.com/user-attachments/assets/2409abdc-847a-4fbd-ac51-ba996174226d)


---

### Features

* Track time spent on projects and subprojects
* Start and stop timers directly in the browser
* Browse and search session history
* Visualize data with charts, scatter plots, and heatmaps (via Chart.js)
* Generate word clouds from session notes
* Export and import data in JSON format (compatible with the old CLI version)
* Ask natural language questions about your data with LLM integration (optional)
* Light and dark themes, with optional Bing daily wallpaper

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
python manage.py runserver
```

Optional:

```bash
python manage.py createsuperuser  # For admin access
```

Access the app at `http://127.0.0.1:8000/`

---

### Tech Stack

* **Backend**: Django, Django REST Framework, SQLite
* **Frontend**: HTML/CSS/JS (jQuery), Chart.js, wordcloud2.js
* **LLM**: Gemini API integration with in-memory handlers
* **Import/Export**: JSON-based, compatible with Autumn CLI
* **No analytics or tracking**

---

### API Docs

See `docs/api.md` for a reference of `/api/*` endpoints (used by the CLI wrapper).

---

> Built with care. Use it if it's useful to you.
