# Install Python Backend + Vite Frontend

Install and run both app surfaces locally.

## Prereqs

- Python `3.12+`
- `uv` installed
- Node.js `20+` and `npm`
- 1Password CLI (`op`) if you use `task api` with `.env.dev`

## Backend (Python/FastAPI)

Install Python dependencies:

```bash
uv sync
```

Start backend directly:

```bash
uv run uvicorn src.api.main:app --reload --port 8000
```

Or start with task + env injection:

```bash
task api
```

## Frontend (React/Vite)

Install frontend dependencies:

```bash
cd frontend
npm install
```

Start Vite dev server:

```bash
npm run dev
```

Frontend runs on `http://localhost:5173` and calls API on `http://localhost:8000`.

## Run Both

In separate terminals:

```bash
task api
task frontend
```

## Optional: DB + Positions Bootstrap

If you need live positions from IBKR:

```bash
op run --env-file=.env.dev -- uv run python scripts/setup_db.py --env dev
op run --env-file=.env.dev -- uv run python scripts/download_positions.py --env dev
```
