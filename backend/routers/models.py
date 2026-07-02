"""Runtime LLM model selection (lets the UI switch models without a restart)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.dependencies import current_user_id
from backend.runtime import available_models, get_active_model, set_active_model

router = APIRouter(prefix="/models", tags=["models"])


class SelectModel(BaseModel):
    model: str


@router.get("")
def list_models(user_id: str = Depends(current_user_id)) -> dict:
    return {"active": get_active_model(), "available": available_models()}


@router.post("/select")
def select_model(req: SelectModel, user_id: str = Depends(current_user_id)) -> dict:
    if req.model not in available_models():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown model."
        )
    set_active_model(req.model)
    return {"active": req.model}
