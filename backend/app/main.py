import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .jobs import scheduler
from .routers import admin, auth, misc, opps, records

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    task = asyncio.create_task(scheduler()) if os.getenv("DISABLE_JOBS") != "1" else None
    yield
    if task:
        task.cancel()


# API 문서는 개발 모드에서만 연다.
app = FastAPI(
    title="SalesNote", lifespan=lifespan, redoc_url=None,
    docs_url="/api/docs" if settings.dev_login else None,
    openapi_url="/api/openapi.json" if settings.dev_login else None,
)


@app.middleware("http")
async def guard(request: Request, call_next):
    """상태를 바꾸는 요청은 화면이 붙이는 헤더가 있어야 받는다(교차 사이트 요청 차단)."""
    if (request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("x-salesnote") != "1"):
        return JSONResponse({"detail": "잘못된 요청입니다."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith(("/api", "/auth")):
        response.headers["Cache-Control"] = "no-store"
    return response


# 세션 쿠키는 서명만 하고 사용자 번호와 마지막 사용 시각만 담는다.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="salesnote_session",
    max_age=settings.session_idle_minutes * 60,
    same_site="lax",
    https_only=settings.cookie_secure,
)

for module in (auth, opps, records, misc, admin):
    app.include_router(module.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
