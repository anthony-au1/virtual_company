from fastapi import FastAPI

from virtual_company.api.campaigns import router as campaigns_router
from virtual_company.api.companies import router as companies_router

app = FastAPI()

app.include_router(campaigns_router)
app.include_router(companies_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
