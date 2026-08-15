# Global Health Dataset Catalog

Small React + FastAPI app for cataloging official health dataset pages.

The app does not download datasets. It stores links to official dataset pages in SQLite
and exposes them through a small API. Dataset pages are organized by theme.

## Structure

- `backend/app/main.py`: FastAPI app setup, CORS, startup, and router registration
- `backend/app/database.py`: SQLite schema, migrations, seed data, and queries
- `backend/app/routes/sources.py`: `/sources` API routes for dataset page links
- `backend/global_health.db`: local SQLite database created by the backend
- `frontend/src/App.jsx`: React UI that reads and displays dataset links
- `tests/test_database.py`: database structure and seed test

## Backend

Install dependencies:

```bash
cd backend
../.venv/bin/pip install -r requirements.txt
```

Run the API:

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload --port 8001
```

Useful endpoints:

```txt
GET  /health
GET  /sources
POST /sources
GET  /sources/{id}/page
```

Example:

```bash
curl -i http://127.0.0.1:8001/sources
```

Add a dataset page:

```bash
curl -i -X POST http://127.0.0.1:8001/sources \
  -H "Content-Type: application/json" \
  -d '{"source_key":"who_data_portal","name":"WHO Data","description":"WHO data portal","theme":"General","page_url":"https://platform.who.int/data"}'
```

## Frontend

Run the React app against the backend on port `8001`:

```bash
cd frontend
VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

Open:

```txt
http://127.0.0.1:5173/
```

## Checks

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest
npm --prefix frontend run build
```
