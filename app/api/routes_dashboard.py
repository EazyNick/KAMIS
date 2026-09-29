from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_web_root = Path(__file__).resolve().parents[1] / "web"
_dashboard = _web_root / "dashboard.html"
_enhancements = _web_root / "dashboard_enhancements.html"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    html = _dashboard.read_text(encoding="utf-8")
    enhancements = _enhancements.read_text(encoding="utf-8")
    return HTMLResponse(html.replace("</body>", f"{enhancements}\n</body>"))
