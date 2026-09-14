from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from virtual_company.api.campaigns import router as campaigns_router
from virtual_company.api.companies import router as companies_router
from virtual_company.tools import WebSearchConfigurationError


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
