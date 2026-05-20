from fastapi import APIRouter, Depends

from app.webhooks._auth import verify_webhook_token
from app.webhooks.elastalert import router as elastalert_router
from app.webhooks.prometheus import router as prometheus_router
from app.webhooks.xxl_job import router as xxl_job_router
from app.webhooks.zabbix import router as zabbix_router

webhook_router = APIRouter(
    prefix="/api/v1/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(verify_webhook_token)],
)
webhook_router.include_router(zabbix_router)
webhook_router.include_router(prometheus_router)
webhook_router.include_router(elastalert_router)
webhook_router.include_router(xxl_job_router)

__all__ = ["webhook_router"]
