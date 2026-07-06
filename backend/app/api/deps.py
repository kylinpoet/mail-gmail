from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_secret
from app.models import ApiKey
from app.services.json_helpers import loads_list


def require_admin(x_admin_token: Optional[str] = Header(None)) -> None:
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")


def get_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key")
    key_hash = hash_secret(x_api_key)
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True)).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="invalid API key")
    ip_allowlist = loads_list(api_key.ip_allowlist)
    client_host = request.client.host if request.client else ""
    if ip_allowlist and client_host not in ip_allowlist:
        raise HTTPException(status_code=403, detail="IP not allowed")
    return api_key
