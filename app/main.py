from fastapi import FastAPI

from app.agents import MainAgent
from app.api import router
from app.config import get_settings
from app.datasources import build_data_source
from app.llm import build_llm_client
from app.reports import ReportGenerator
from app.storage import JsonDiagnosisStore
from app.webhooks import webhook_router
from app.webhooks._dedup import DeduplicationService
from app.workflow import WorkflowEngine


def create_app() -> FastAPI:
    settings = get_settings()
    llm_client = build_llm_client(settings)
    agents = MainAgent(settings, llm_client)
    data_source = build_data_source(settings)
    store = JsonDiagnosisStore(settings.runtime_dir)
    workflow_engine = WorkflowEngine(
        agents=agents,
        data_source=data_source,
        store=store,
        low_confidence_threshold=settings.low_confidence_threshold,
    )

    app = FastAPI(title="AI Diagnostic Agent", version="0.1.0")
    app.state.settings = settings
    app.state.workflow_engine = workflow_engine
    app.state.report_generator = ReportGenerator()
    app.state.dedup_service = DeduplicationService(settings.webhook_dedup_cooldown_seconds)
    app.include_router(router)
    app.include_router(webhook_router)
    return app


app = create_app()
