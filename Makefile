.PHONY: install dev-backend dev-frontend test lint demo docker

install:            ## Create the Python venv and install all dependencies
	python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
	cd frontend && npm ci

dev-backend:        ## FastAPI on :8000 (auto-reload)
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

dev-frontend:       ## Vite on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

test:               ## Backend tests
	cd backend && ../.venv/bin/pytest -q

lint:               ## Lint + format check + typecheck
	cd backend && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
	cd frontend && npm run typecheck

docker:             ## Whole stack in Docker on http://localhost:8080
	docker compose up --build
