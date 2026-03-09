from __future__ import annotations

from fastapi import FastAPI
import logging
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from .config import load_config
from .routes.submissions import router as submissions_router
from .routes.nodes import router as nodes_router
from .routes.presign import router as presign_router
from .routes.ui import router as ui_router
from .storage import Storage, StorageConfig
from .workers.dispatcher import Dispatcher
from .nomad_inventory import NomadInventory

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="fedctl submit service")

    cfg = load_config()
    if cfg.ui_enabled and not cfg.ui_session_secret:
        raise RuntimeError(
            "SUBMIT_UI_SESSION_SECRET must be set when SUBMIT_UI_ENABLED=true"
        )
    logger.info(
        "submit-service config: endpoint=%s tokens=%s allow_unauth=%s dispatch_mode=%s ui_enabled=%s",
        cfg.service_endpoint or "-",
        "set" if (cfg.tokens or cfg.token_identities) else "empty",
        cfg.allow_unauth,
        cfg.dispatch_mode,
        cfg.ui_enabled,
    )
    storage = Storage(StorageConfig(db_url=cfg.db_url))
    storage.init_db()

    app.state.cfg = cfg
    app.state.storage = storage
    app.state.dispatcher = Dispatcher(storage, cfg)
    app.state.inventory = NomadInventory(cfg)

    if cfg.ui_enabled:
        static_dir = Path(__file__).resolve().parent / "static"
        app.add_middleware(
            SessionMiddleware,
            secret_key=cfg.ui_session_secret,
            session_cookie=cfg.ui_cookie_name,
            https_only=cfg.ui_cookie_secure,
            same_site="lax",
        )
        app.mount("/ui/static", StaticFiles(directory=str(static_dir)), name="ui-static")

    app.include_router(submissions_router)
    app.include_router(nodes_router)
    app.include_router(presign_router)
    if cfg.ui_enabled:
        app.include_router(ui_router)

    @app.on_event("startup")
    def _start_dispatcher() -> None:
        if cfg.dispatch_mode == "queue":
            app.state.dispatcher.start()

    @app.on_event("shutdown")
    def _stop_dispatcher() -> None:
        app.state.dispatcher.stop()

    return app


app = create_app()
