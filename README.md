## Run

docker compose up --build uv run alembic upgrade head

uv run uvicorn virtual_company.main:app --reload