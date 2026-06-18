"""Experiments API routes (Layer 14). Lazy FastAPI via factory."""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


def get_router(manager: Any | None = None):  # pragma: no cover - requires fastapi
    """Build the experiments APIRouter against a shared ABTestManager."""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    from experiments.ab_test_manager import ABTestManager

    mgr = manager or ABTestManager()
    router = APIRouter(prefix="/experiments", tags=["experiments"])

    class CreateRequest(BaseModel):
        name: str
        variants: list[str]
        traffic_split: list[float]

    @router.post("")
    def create(req: CreateRequest) -> dict[str, str]:
        try:
            exp_id = mgr.create_experiment(req.name, req.variants, req.traffic_split)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"experiment_id": exp_id}

    @router.get("/{experiment_id}/assign")
    def assign(experiment_id: str, unit_id: str) -> dict[str, str]:
        try:
            return {"variant": mgr.assign_variant(experiment_id, unit_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{experiment_id}/results")
    def results(experiment_id: str) -> dict[str, Any]:
        try:
            return mgr.get_results(experiment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
