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

## Agent Documentation and Context Recovery

Canonical project documentation is indexed in `docs/README.md`. For a new
conversation with no project context, use **Full Context Recovery**: read this
file, `docs/README.md`, every canonical document linked there (including both
workflow guides), and `frontend/AGENTS.md`; then verify implementation details
against the referenced source. You should be able to explain the product,
current status, architecture, workflows, data relationships, integrations, and
recorded decisions without relying on prior chat history. Mark unknown or
unverified details as such instead of guessing.

For a regular task, use **Task-Specific Context**: read this file,
`docs/README.md`, `docs/overview.md`, and `docs/architecture.md`, then follow
the relevant path in the index. Before changing implementation, inspect its
source and tests. Update canonical docs when behavior, data contracts, or
operational semantics change.

Task reading paths are maintained in `docs/README.md`: Research,
Exploration, shared workflow execution, database/persistence, frontend,
LLM/integrations, and infrastructure/operations. Frontend changes also follow
`frontend/AGENTS.md`.
