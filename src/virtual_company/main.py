import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from virtual_company.api.campaigns import router as campaigns_router
from virtual_company.api.explorations import router as explorations_router
from virtual_company.api.research_companies import router as companies_router
from virtual_company.api.research_runs import router as research_runs_router
from virtual_company.config import get_settings
from virtual_company.db.session import session_factory
from virtual_company.task_queue.broker import broker
from virtual_company.task_queue.reconciliation import run_reconciliation_loop
from virtual_company.tools import WebSearchConfigurationError


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Configure optional telemetry for the application process."""
    from virtual_company.observability import (
        configure_observability,
        shutdown_observability,
    )

    settings = get_settings()
    configure_observability(settings)
    await broker.startup()
    reconciler: asyncio.Task[None] | None = None
    if settings.taskiq_reconciliation_enabled:
        reconciler = asyncio.create_task(
            run_reconciliation_loop(session_factory, settings),
            name="taskiq-run-reconciler",
        )
    try:
        yield
    finally:
        if reconciler is not None:
            reconciler.cancel()
            with suppress(asyncio.CancelledError):
                await reconciler
        try:
            await broker.shutdown()
        finally:
            shutdown_observability()


app = FastAPI(lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)

app.include_router(campaigns_router)
app.include_router(explorations_router)
app.include_router(companies_router)
app.include_router(research_runs_router)


@app.exception_handler(WebSearchConfigurationError)
async def web_search_configuration_error_handler(
    _request: Request, error: WebSearchConfigurationError
) -> JSONResponse:
    """Expose selected-provider configuration failures as a service-unavailable response."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(error)},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
