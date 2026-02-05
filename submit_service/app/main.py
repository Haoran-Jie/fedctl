from __future__ import annotations

from fastapi import FastAPI
import logging

from .config import load_config
from .routes.submissions import router as submissions_router
from .routes.nodes import router as nodes_router
from .routes.presign import router as presign_router
from .storage import Storage, StorageConfig
from .workers.dispatcher import Dispatcher
from .nomad_inventory import NomadInventory

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="fedctl submit service")

    cfg = load_config()
    logger.info(
        "submit-service config: endpoint=%s tokens=%s allow_unauth=%s dispatch_mode=%s",
        cfg.service_endpoint or "-",
        "set" if cfg.tokens else "empty",
        cfg.allow_unauth,
        cfg.dispatch_mode,
    )
    storage = Storage(StorageConfig(db_url=cfg.db_url))
    storage.init_db()

    app.state.cfg = cfg
    app.state.storage = storage
    app.state.dispatcher = Dispatcher(storage, cfg)
    app.state.inventory = NomadInventory(cfg)

    app.include_router(submissions_router)
    app.include_router(nodes_router)
    app.include_router(presign_router)

    @app.on_event("startup")
    def _start_dispatcher() -> None:
        if cfg.dispatch_mode == "queue":
            app.state.dispatcher.start()

    @app.on_event("shutdown")
    def _stop_dispatcher() -> None:
        app.state.dispatcher.stop()

    return app


app = create_app()
