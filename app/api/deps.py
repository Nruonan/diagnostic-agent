from fastapi import Request

from app.config import Settings
from app.events import WorkflowEventBus
from app.reports import ReportGenerator
from app.workflow import WorkflowEngine


def get_engine(request: Request) -> WorkflowEngine:
    return request.app.state.workflow_engine


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_report_generator(request: Request) -> ReportGenerator:
    return request.app.state.report_generator


def get_event_bus(request: Request) -> WorkflowEventBus:
    return request.app.state.event_bus
