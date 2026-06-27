from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.sources.ntes import (
    NTESFetchError,
    ntes_exceptions,
    ntes_live_status,
    ntes_schedule,
    ntes_train_info,
)

router = APIRouter()


@router.get("/trains/{train_no}")
def get_train_info(train_no: str):
    train_no_value = train_no.strip()
    if not train_no_value:
        raise HTTPException(status_code=400, detail="Missing required path parameter: train_no")
    try:
        return ntes_train_info(train_no_value)
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/trains/{train_no}/schedule")
def get_train_schedule(
    train_no: str,
    date: Optional[str] = Query(None, description="Journey start date in DD-MMM-YYYY format"),
):
    train_no_value = train_no.strip()
    if not train_no_value:
        raise HTTPException(status_code=400, detail="Missing required path parameter: train_no")
    try:
        return ntes_schedule(train_no_value, date.strip() if date else "")
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/trains/{train_no}/live-status")
def get_live_status(
    train_no: str,
    date: str = Query(..., description="Journey start date in DD-MMM-YYYY format"),
):
    train_no_value = train_no.strip()
    date_value = date.strip()
    if not train_no_value:
        raise HTTPException(status_code=400, detail="Missing required path parameter: train_no")
    if not date_value:
        raise HTTPException(status_code=400, detail="Missing required query parameter: date")
    try:
        return ntes_live_status(train_no_value, date_value)
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/trains/{train_no}/exceptions")
def get_train_exceptions(train_no: str):
    train_no_value = train_no.strip()
    if not train_no_value:
        raise HTTPException(status_code=400, detail="Missing required path parameter: train_no")
    try:
        return ntes_exceptions(train_no_value)
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
