"""Application entrypoint: FastAPI app assembly.

Run:  uvicorn app.main:app --host 127.0.0.1 --port 8000
      python -m app.main
"""
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core import database, settings, maintenance, tasks
from .automation import browser, fpcheck, scheduler, token_refresh
from .routers import auth_router, groups_router, accounts_router, system_router, proxies_router

WEB_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# Provider URLs carry credentials in query strings; never log them at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    await settings.init_settings()
    await maintenance.prune_once()          # startup sweep
    pruner = maintenance.start_pruner()     # hourly sweep
    token_refresher = token_refresh.start_scheduler(
        groups_router.run_due_token_refresh)
    yield
    pruner.cancel()
    token_refresher.cancel()
    await fpcheck.shutdown_checks()
    await tasks.cancel_all()
    await scheduler.shutdown()
    await browser.close_all_managed_sessions()
    await database.close_db()


app = FastAPI(title="freedom-accounts", lifespan=lifespan)

app.include_router(auth_router.router)
app.include_router(groups_router.router)
app.include_router(accounts_router.router)
app.include_router(system_router.router)
app.include_router(proxies_router.router)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(WEB_DIR / "index.html")


# static assets (css/js) under /static
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    from .core import config
    uvicorn.run(app, host=config.HOST, port=config.PORT)
