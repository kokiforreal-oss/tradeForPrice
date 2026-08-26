from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.core.e2e import org_key_b64
from app.db.models import User

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


@router.get("/org-key")
def get_org_key(_: Annotated[User, Depends(get_current_user)]):
    return {"alg": "AES-256-GCM", "key_b64": org_key_b64()}
