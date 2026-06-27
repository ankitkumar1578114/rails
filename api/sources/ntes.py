import os
from typing import Any, Dict, Optional

from ntes import NTESClient, NTESError


class NTESFetchError(RuntimeError):
    pass


_client: Optional[NTESClient] = None


def get_ntes_client() -> NTESClient:
    global _client
    if _client is None:
        timeout = int(os.environ.get("NTES_TIMEOUT", "15"))
        retries = int(os.environ.get("NTES_RETRIES", "2"))
        _client = NTESClient(timeout=timeout, retries=retries)
    return _client


def _call_ntes(method: str, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    try:
        return getattr(get_ntes_client(), method)(*args, **kwargs)
    except NTESError as exc:
        raise NTESFetchError(str(exc)) from exc


def ntes_search(query: str) -> Dict[str, Any]:
    return _call_ntes("search", query)


def ntes_train_info(train_no: str) -> Dict[str, Any]:
    return _call_ntes("train_info", train_no)


def ntes_schedule(train_no: str, start_date: str = "") -> Dict[str, Any]:
    return _call_ntes("schedule", train_no, start_date)


def ntes_station_live(station_code: str, hours: int = 2) -> Dict[str, Any]:
    return _call_ntes("station_live", station_code, hours)


def ntes_live_status(train_no: str, start_date: str) -> Dict[str, Any]:
    return _call_ntes("live_status", train_no, start_date)


def ntes_exceptions(train_no: str) -> Dict[str, Any]:
    return _call_ntes("exceptions", train_no)


def ntes_pnr_status(pnr: str) -> Dict[str, Any]:
    return _call_ntes("pnr_status", pnr)


def ntes_trains_between(from_station: str, to_station: str, train_type: str = "XXX") -> Dict[str, Any]:
    return _call_ntes("trains_between", from_station, to_station, train_type)
