from __future__ import annotations

from fastapi import FastAPI

from .config import load_config
from .routes.submissions import router as submissions_router
from .storage import Storage, StorageConfig
from .workers.dispatcher import Dispatcher


def create_app() -> FastAPI:
    app = FastAPI(title="fedctl submit service")

    cfg = load_config()
    storage = Storage(StorageConfig(db_url=cfg.db_url))
    storage.init_db()

    app.state.cfg = cfg
    app.state.storage = storage
    app.state.dispatcher = Dispatcher(storage, cfg)

    app.include_router(submissions_router)

    @app.on_event("startup")
    def _start_dispatcher() -> None:
        if cfg.dispatch_mode == "queue":
            app.state.dispatcher.start()

    @app.on_event("shutdown")
    def _stop_dispatcher() -> None:
        app.state.dispatcher.stop()

    return app


app = create_app()
