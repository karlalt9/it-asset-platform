"""FastAPI 应用入口。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import agents, alerts, devices, stats
from .config import settings
from .database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="终端巡检上报、资产台账与告警看板",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api/v1")
api.include_router(agents.router)
api.include_router(devices.router)
api.include_router(alerts.router)
api.include_router(stats.router)
app.include_router(api)


@app.get("/api/health", tags=["meta"], summary="健康检查")
def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.version}


def _resolve_web_dist() -> Path | None:
    candidates: list[Path] = []
    env_dir = os.getenv("IAP_WEB_DIST")
    if env_dir:
        candidates.append(Path(env_dir))
    here = Path(__file__).resolve()
    candidates.append(here.parent.parent.parent / "web" / "dist")
    candidates.append(here.parent.parent / "static")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


WEB_DIST = _resolve_web_dist()

if WEB_DIST is not None:
    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        # 前端用 history 路由，刷新子路径时回退到 index.html
        target = WEB_DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")
