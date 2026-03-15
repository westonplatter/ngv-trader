"""Saved option structures API router."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import SavedStructure

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class StructureResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    instrument: str
    legs: list
    spot_price: float | None
    created_at: datetime
    updated_at: datetime


def to_structure_response(s: SavedStructure) -> StructureResponse:
    return StructureResponse(
        id=s.id,
        name=s.name,
        instrument=s.instrument,
        legs=s.legs,
        spot_price=s.spot_price,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@router.get("/structures", response_model=list[StructureResponse])
def list_structures(db: Session = DB_SESSION_DEPENDENCY) -> list[StructureResponse]:
    stmt = select(SavedStructure).order_by(SavedStructure.updated_at.desc())
    rows = db.execute(stmt).scalars().all()
    return [to_structure_response(s) for s in rows]


@router.get("/structures/{structure_id}", response_model=StructureResponse)
def get_structure(structure_id: int, db: Session = DB_SESSION_DEPENDENCY) -> StructureResponse:
    s = db.get(SavedStructure, structure_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Structure not found")
    return to_structure_response(s)


class CreateStructureRequest(BaseModel):
    name: str
    instrument: str
    legs: list
    spot_price: float | None = None


@router.post("/structures", response_model=StructureResponse, status_code=201)
def create_structure(
    body: CreateStructureRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> StructureResponse:
    now = datetime.now(timezone.utc)
    s = SavedStructure(
        name=body.name,
        instrument=body.instrument,
        legs=body.legs,
        spot_price=body.spot_price,
        created_at=now,
        updated_at=now,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return to_structure_response(s)


class UpdateStructureRequest(BaseModel):
    name: str
    instrument: str
    legs: list
    spot_price: float | None = None


@router.put("/structures/{structure_id}", response_model=StructureResponse)
def update_structure(
    structure_id: int,
    body: UpdateStructureRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> StructureResponse:
    s = db.get(SavedStructure, structure_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Structure not found")
    s.name = body.name
    s.instrument = body.instrument
    s.legs = body.legs
    s.spot_price = body.spot_price
    s.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return to_structure_response(s)


@router.delete("/structures/{structure_id}", status_code=204)
def delete_structure(
    structure_id: int,
    db: Session = DB_SESSION_DEPENDENCY,
) -> None:
    s = db.get(SavedStructure, structure_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Structure not found")
    db.delete(s)
    db.commit()
