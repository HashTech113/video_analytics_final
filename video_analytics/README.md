# Video Analytics Workspace

This repository contains a FastAPI backend and a React/Vite frontend for video person-count analytics.

## Project structure

- `backend/`: upload, processing, analytics APIs, and generated artifacts
- `frontend/`: dashboard and upload UI

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm

## Run both services from repo root

Install frontend dependencies first:

```bash
cd frontend
npm install
cd ..
```

Start backend + frontend together:

```bash
npm run all
```

(`npm run full` is also supported.)

```bash
npm run full
```

Start backend + frontend with public host binding (EC2/LAN):

```bash
npm run full:public
```

Default URLs:

- Frontend (workspace script): `http://localhost:5173`
- Backend API: `http://localhost:8000`
- EC2 example: `http://<EC2_PUBLIC_IP>:5173` and `http://<EC2_PUBLIC_IP>:8000`

## Run services separately

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Default frontend dev URL (direct frontend command): `http://localhost:5173`

For EC2/external access, start with host binding:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
npm run dev -- --host 0.0.0.0 --port 5173
```

## Notes

- Generated files are written to `backend/uploads/` and `backend/outputs/`.
- Dashboard behavior:
  - `Total Videos` always shows overall processed-video count.
  - Other analytics are shown after selecting a video via `View`.
