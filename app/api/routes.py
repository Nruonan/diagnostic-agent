from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.config import Settings
from app.reports import ReportGenerator
from app.schemas.diagnosis import DiagnosisCreate, DiagnosisResponse, DiagnosisStatus, HumanInputCreate
from app.schemas.reports import ReportResponse
from app.workflow import WorkflowEngine

router = APIRouter()


def get_engine(request: Request) -> WorkflowEngine:
    return request.app.state.workflow_engine


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_report_generator(request: Request) -> ReportGenerator:
    return request.app.state.report_generator


@router.get("/health")
async def health(settings: Settings = Depends(get_settings_from_app)) -> dict:
    return {
        "status": "ok",
        "dashscope_configured": settings.dashscope_configured(),
        "data_source_mode": settings.data_source_mode,
    }


@router.post("/api/v1/diagnoses", response_model=DiagnosisResponse)
async def create_diagnosis(
    payload: DiagnosisCreate,
    engine: WorkflowEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings_from_app),
) -> DiagnosisResponse:
    if not settings.dashscope_configured():
        raise HTTPException(status_code=503, detail="DASHSCOPE_API_KEY is not configured")
    return DiagnosisResponse(diagnosis=await engine.start(payload))


@router.get("/api/v1/diagnoses/{diagnosis_id}", response_model=DiagnosisResponse)
async def get_diagnosis(diagnosis_id: str, engine: WorkflowEngine = Depends(get_engine)) -> DiagnosisResponse:
    return DiagnosisResponse(diagnosis=await engine.get(diagnosis_id))


@router.post("/api/v1/diagnoses/{diagnosis_id}/input", response_model=DiagnosisResponse)
async def add_human_input(
    diagnosis_id: str,
    payload: HumanInputCreate,
    engine: WorkflowEngine = Depends(get_engine),
) -> DiagnosisResponse:
    state = await engine.get(diagnosis_id)
    if state.status != DiagnosisStatus.NEED_USER_INPUT:
        raise HTTPException(status_code=409, detail=f"diagnosis status is {state.status.value}, not need_user_input")
    return DiagnosisResponse(diagnosis=await engine.add_human_input(diagnosis_id, payload.content))


@router.get("/api/v1/reports/{diagnosis_id}", response_model=ReportResponse)
async def get_report(diagnosis_id: str, engine: WorkflowEngine = Depends(get_engine)) -> ReportResponse:
    state = await engine.get(diagnosis_id)
    if state.status not in {DiagnosisStatus.COMPLETED, DiagnosisStatus.NEED_USER_INPUT, DiagnosisStatus.FAILED}:
        raise HTTPException(status_code=409, detail=f"diagnosis status is {state.status.value}")
    return ReportResponse(diagnosis_id=diagnosis_id, report=state)


@router.get("/api/v1/reports/{diagnosis_id}/markdown", response_class=PlainTextResponse)
async def get_report_markdown(
    diagnosis_id: str,
    engine: WorkflowEngine = Depends(get_engine),
    generator: ReportGenerator = Depends(get_report_generator),
) -> str:
    state = await engine.get(diagnosis_id)
    if state.status not in {DiagnosisStatus.COMPLETED, DiagnosisStatus.NEED_USER_INPUT, DiagnosisStatus.FAILED}:
        raise HTTPException(status_code=409, detail=f"diagnosis status is {state.status.value}")
    return generator.to_markdown(state)

