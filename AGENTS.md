# Project instructions

## Project
This is an AI-assisted virtual company.

Backend:
- Python 3.12
- FastAPI
- SQLAlchemy 2.x
- PostgreSQL
- Alembic
- uv for dependency management

## Architecture

Use layered architecture:

src/
  api/
  domain/
  services/
  repositories/
  db/

Domain logic must not depend on FastAPI.

Database access must go through SQLAlchemy repositories.

## Database

Database design is documented in:
docs/database-schema.md

Domain model is documented in:
docs/domain-model.md

When modifying persistence:
- use SQLAlchemy declarative models
- create Alembic migrations
- do not use raw SQL unless necessary
- use UUID primary keys unless the specification says otherwise
- use PostgreSQL TIMESTAMPTZ for timestamps

## Coding conventions

- Python type hints everywhere
- Prefer dataclasses / Pydantic models for DTOs
- Avoid large functions
- Keep business logic outside API handlers
- Use async database access

## Tests

After modifications run:

uv run pytest

For schema changes also verify:

uv run alembic upgrade head

## Working rules

Before implementing a feature:
1. inspect the existing code
2. inspect relevant files under docs/
3. explain the proposed changes
4. implement the smallest coherent change
5. run tests

Do not redesign unrelated parts of the application.
