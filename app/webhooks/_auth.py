from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.api.deps import get_settings_from_app
from app.config import Settings


async def verify_webhook_token(
    x_webhook_token: Annotated[str | None, Header(alias="X-Webhook-Token")] = None,
    settings: Settings = Depends(get_settings_from_app),
) -> None:
    expected_token = settings.webhook_token.strip()
    if not expected_token:
        return
    if x_webhook_token != expected_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook token")
