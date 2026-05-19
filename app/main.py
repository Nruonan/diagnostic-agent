from fastapi import FastAPI

from app.agents import MainAgent
from app.api import router
from app.config import get_settings
from app.datasources import build_data_source
from app.reports import ReportGenerator
from app.storage import JsonDiagnosisStore
from app.workflow import WorkflowEngine


def create_app() -> FastAPI:
    settings = get_settings()
    agents = MainAgent(settings)
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
    app.include_router(router)
    return app


app = create_app()

