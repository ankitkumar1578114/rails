from fastapi import APIRouter, HTTPException

from api.sources.ntes import NTESFetchError, ntes_pnr_status

router = APIRouter()


@router.get("/pnr/{pnr}")
def get_pnr_status(pnr: str):
    pnr_value = pnr.strip()
    if not pnr_value.isdigit() or len(pnr_value) != 10:
        raise HTTPException(status_code=400, detail="PNR must be a 10-digit number")
    try:
        return ntes_pnr_status(pnr_value)
    except NTESFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
