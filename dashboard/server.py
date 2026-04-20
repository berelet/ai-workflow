"""AI Workflow Dashboard — FastAPI application entry point.

All business logic is in routers/ and services/.
This file is the thin app factory: middleware, router includes, UI serving.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent.parent
load_dotenv(str(BASE / ".env"))
load_dotenv(str(BASE / ".env.local"), override=True)  # local overrides if exists

UPLOAD_DIR = BASE / "tmp" / "terminal-uploads"
UPLOAD_MAX_AGE = 86400  # 1 day in seconds


async def _cleanup_uploads():
    """Periodically delete uploaded temp files older than 1 day."""
    while True:
        await asyncio.sleep(3600)  # check every hour
        try:
            if not UPLOAD_DIR.exists():
                continue
            now = time.time()
            for f in UPLOAD_DIR.iterdir():
                if f.is_file() and (now - f.stat().st_mtime) > UPLOAD_MAX_AGE:
                    f.unlink()
        except Exception:
            pass


async def _ensure_dashboard_instance_registered():
    """Make sure DASHBOARD_UUID exists in the dashboard_instances table.

    The setup wizard inserts this row on first install, but a fresh deploy
    that bypasses the wizard (e.g. rsync/git deploy onto a new host with
    a hand-set DASHBOARD_UUID) ends up with an orphan UUID — any attempt
    to write instance_project_bindings then fails with FK violation.
    Inserting on startup makes the system self-bootstrapping.
    """
    import logging, os, socket, uuid as _uuid
    raw = (os.environ.get("DASHBOARD_UUID") or "").strip()
    if not raw:
        return
    try:
        instance_uuid = _uuid.UUID(raw)
    except ValueError:
        return
    from sqlalchemy import select
    from dashboard.db.engine import async_session as async_session_factory
    from dashboard.db.models.dashboard_instance import DashboardInstance
    log = logging.getLogger("server")
    try:
        async with async_session_factory() as db:
            existing = (await db.execute(
                select(DashboardInstance).where(DashboardInstance.id == instance_uuid)
            )).scalar_one_or_none()
            if existing:
                return
            db.add(DashboardInstance(id=instance_uuid, hostname=socket.gethostname()))
            await db.commit()
            log.info("Registered new dashboard instance %s (%s)", instance_uuid, socket.gethostname())
    except Exception as e:
        log.warning("Could not register dashboard instance: %s", e)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(_cleanup_uploads())
    # Seed global pipeline templates + architect agent on first run
    try:
        from dashboard.db.seed_templates import seed_all
        if await seed_all():
            import logging
            logging.getLogger("server").info("Seeded global pipeline templates")
    except Exception:
        pass
    # Self-register this dashboard instance if missing (for non-wizard deploys)
    await _ensure_dashboard_instance_registered()
    yield
    task.cancel()


app = FastAPI(title="AI Workflow", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok"}
app.mount("/static", StaticFiles(directory=str(BASE / "dashboard" / "static")), name="static")

# --- API Routers ---
from dashboard.auth.routes import router as auth_router
from dashboard.admin.routes import router as admin_router
from dashboard.setup.wizard import router as setup_router
from dashboard.routers.pipeline import router as pipeline_router
from dashboard.routers.projects import router as projects_router
from dashboard.routers.agents import router as agents_router
from dashboard.routers.terminal import router as terminal_router
from dashboard.routers.telemetry import router as telemetry_router
from dashboard.routers.services import router as services_router
from dashboard.routers.transcriber import router as transcriber_router
from dashboard.routers.catalog import router as catalog_router
from dashboard.routers.notifications import router as notifications_router
from dashboard.routers.queue import router as queue_router
from dashboard.routers.git_ops import router as git_ops_router

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(setup_router)
app.include_router(pipeline_router)
app.include_router(projects_router)
app.include_router(agents_router)
app.include_router(terminal_router)
app.include_router(telemetry_router)
app.include_router(services_router)
app.include_router(transcriber_router)
app.include_router(catalog_router)
app.include_router(notifications_router)
app.include_router(queue_router)
app.include_router(git_ops_router)

# --- UI Router (Jinja2 pages + HTMX partials) ---
from dashboard.routers.ui import router as ui_router
app.include_router(ui_router)
