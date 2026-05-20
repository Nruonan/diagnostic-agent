from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.api.deps import get_engine, get_report_generator, get_settings_from_app
from app.config import Settings
from app.reports import ReportGenerator
from app.schemas.alerts import AlertEventCreate
from app.schemas.diagnosis import DiagnosisCreate, DiagnosisResponse, DiagnosisStatus, HumanInputCreate
from app.schemas.reports import ReportResponse
from app.workflow import WorkflowEngine

router = APIRouter()


@router.get("/health")
async def health(settings: Settings = Depends(get_settings_from_app)) -> dict:
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "llm_configured": settings.llm_configured(),
        "dashscope_configured": settings.dashscope_configured(),
        "data_source_mode": settings.data_source_mode,
    }


@router.post("/api/v1/diagnoses", response_model=DiagnosisResponse)
async def create_diagnosis(
    payload: DiagnosisCreate,
    engine: WorkflowEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings_from_app),
) -> DiagnosisResponse:
    if not settings.llm_configured():
        raise HTTPException(status_code=503, detail=settings.llm_missing_configuration_message())
    return DiagnosisResponse(diagnosis=await engine.start(payload))


@router.post("/api/v1/alerts", response_model=DiagnosisResponse, status_code=202)
async def ingest_alert(
    payload: AlertEventCreate,
    background_tasks: BackgroundTasks,
    engine: WorkflowEngine = Depends(get_engine),
    settings: Settings = Depends(get_settings_from_app),
) -> DiagnosisResponse:
    if not settings.llm_configured():
        raise HTTPException(status_code=503, detail=settings.llm_missing_configuration_message())
    request = payload.to_diagnosis_create()
    state = await engine.create(
        request,
        trigger_source="alert",
        trigger_context=payload.model_dump(mode="json"),
    )
    background_tasks.add_task(engine.run, state.diagnosis_id)
    return DiagnosisResponse(diagnosis=state)


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
