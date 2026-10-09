"""
Ghost_Alert backend (v1 design, demo subset).
Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import api, db, ingest
from .config import load_settings
from .notify import Notifier
from .store import InfluxStore, MemoryStore
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings=None, engine=None, store=None, notifier=None, start_background=True):
    settings = settings or load_settings()
    engine = engine or db.make_engine(settings.pg_url)
    if store is None:
        if settings.telemetry_store == "memory":
            logging.getLogger("ghost_alert").warning("TELEMETRY_STORE=memory: readings are lost on restart")
            store = MemoryStore()
        else:
            store = InfluxStore(settings.influx_url, settings.influx_token,
                                settings.influx_org, settings.influx_bucket)
    notifier = notifier or Notifier(settings.telegram_bot_token, settings.telegram_chat_id)
    worker = Worker(engine, store, notifier, settings.dashboard_url, settings.safety_round_s)

    @asynccontextmanager
    async def lifespan(app):
        db.apply_schema(engine)
        if start_background:
            notifier.start()
            worker.start()
        yield
        worker.stop()
        notifier.stop()

    app = FastAPI(title="Ghost_Alert API", version="1.0-demo", lifespan=lifespan)
    app.state.settings, app.state.engine, app.state.store = settings, engine, store
    app.state.notifier, app.state.worker = notifier, worker
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.include_router(ingest.router)
    app.include_router(api.router)
    return app


def _lazy_app():
    return create_app()


app = None
try:
    app = _lazy_app()
except Exception as exc:  # pragma: no cover - lets tests import this module without a .env
    logging.getLogger("ghost_alert").warning("app not created at import: %s", exc)
