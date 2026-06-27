from fastapi import APIRouter

from .pnr import router as pnr_router
from .search import router as search_router
from .stations import router as stations_router
from .trains import router as trains_router

router = APIRouter(prefix="/ntes", tags=["ntes"])
router.include_router(search_router)
router.include_router(trains_router)
router.include_router(stations_router)
router.include_router(pnr_router)
