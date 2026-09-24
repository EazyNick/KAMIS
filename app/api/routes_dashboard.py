from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_dashboard = Path(__file__).resolve().parents[1] / "web" / "dashboard.html"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    return HTMLResponse(_dashboard.read_text(encoding="utf-8"))
