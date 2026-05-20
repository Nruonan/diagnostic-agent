from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.agents import MainAgent
from app.api import router
from app.config import get_settings
from app.datasources import build_data_source
from app.events import WorkflowEventBus
from app.llm import build_llm_client
from app.reports import ReportGenerator
from app.storage import build_diagnosis_store
from app.webhooks import webhook_router
from app.webhooks._dedup import DeduplicationService
from app.workflow import WorkflowEngine


def create_app() -> FastAPI:
    settings = get_settings()
    llm_client = build_llm_client(settings)
    agents = MainAgent(settings, llm_client)
    data_source = build_data_source(settings)
    store = build_diagnosis_store(settings)
    event_bus = WorkflowEventBus(store=store)
    workflow_engine = WorkflowEngine(
        agents=agents,
        data_source=data_source,
        store=store,
        low_confidence_threshold=settings.low_confidence_threshold,
        event_bus=event_bus,
    )

    app = FastAPI(title="AI Diagnostic Agent", version="0.1.0")
    app.state.settings = settings
    app.state.store = store
    app.state.workflow_engine = workflow_engine
    app.state.report_generator = ReportGenerator()
    app.state.dedup_service = DeduplicationService(settings.webhook_dedup_cooldown_seconds)
    app.state.event_bus = event_bus
    app.include_router(router)
    app.include_router(webhook_router)

    @app.get("/ui/", include_in_schema=False)
    async def ui_index() -> FileResponse:
        return FileResponse(
            Path(__file__).parent / "static" / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")

    @app.get("/")
    async def index() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    @app.on_event("startup")
    async def initialize_store() -> None:
        await store.initialize()

    @app.on_event("shutdown")
    async def close_store() -> None:
        await store.close()

    return app


app = create_app()
