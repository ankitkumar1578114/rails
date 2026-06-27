from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.sources.ntes import NTESFetchError, ntes_search, ntes_trains_between

router = APIRouter()


@router.get("/search")
def search_trains(
    q: Optional[str] = Query(None, description="Train number, name, or keyword"),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Missing required query parameter: q")
    try:
        return ntes_search(q.strip())
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/trains/between")
def search_trains_between(
    from_station: Optional[str] = Query(None, alias="from", description="Source station code"),
    to_station: Optional[str] = Query(None, alias="to", description="Destination station code"),
    train_type: str = Query("XXX", description="Train type filter (XXX for all types)"),
):
    if not from_station or not from_station.strip() or not to_station or not to_station.strip():
        raise HTTPException(status_code=400, detail="Missing required query parameters: from and to")
    try:
        return ntes_trains_between(
            from_station.strip().upper(),
            to_station.strip().upper(),
            train_type.strip().upper(),
        )
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
