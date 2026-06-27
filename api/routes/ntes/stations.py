from fastapi import APIRouter, HTTPException, Query

from api.sources.ntes import NTESFetchError, ntes_station_live

router = APIRouter()


@router.get("/stations/{station_code}/live")
def get_station_live(
    station_code: str,
    hours: int = Query(2, ge=1, le=24, description="Time window in hours"),
):
    station_code_value = station_code.strip().upper()
    if not station_code_value:
        raise HTTPException(status_code=400, detail="Missing required path parameter: station_code")
    try:
        return ntes_station_live(station_code_value, hours)
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
