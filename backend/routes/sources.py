"""Source CRUD API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.models import SourceCreate, SourceResponse, SourceUpdate
from backend.services.sources import create_source, get_source_dto, list_source_dtos, source_dto

router = APIRouter()


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(request: Request) -> list[dict]:
    return list_source_dtos(request.app.state.db)


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def add_source(body: SourceCreate, request: Request) -> dict:
    try:
        return await create_source(body, request.app.state.db, request.app.state.orchestrator)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(source_id: int, request: Request) -> dict:
    source = get_source_dto(request.app.state.db, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def update_source(source_id: int, body: SourceUpdate, request: Request) -> dict:
    db = request.app.state.db
    source = db.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    updates = body.model_dump(exclude_unset=True)
    if updates:
        db.update_source(source_id, **updates)

    return source_dto(db, db.get_source(source_id))


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int, request: Request) -> None:
    db = request.app.state.db
    if not db.get_source(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete_source(source_id)
