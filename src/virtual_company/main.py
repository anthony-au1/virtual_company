from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from virtual_company.api.campaigns import router as campaigns_router
from virtual_company.api.companies import router as companies_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Configure optional telemetry for the application process."""
    from virtual_company.observability import (
        configure_observability,
        shutdown_observability,
    )

    configure_observability()
    yield
    shutdown_observability()


app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)

app.include_router(campaigns_router)
app.include_router(companies_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
