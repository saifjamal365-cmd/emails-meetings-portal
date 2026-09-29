"""FastAPI app: creates the database, starts the background jobs, checks the login,
registers the API routes and (when it is built) serves the React portal.

Development:  uvicorn app.main:app --reload      (portal: npm run dev on port 5173)
Production:   ENVIRONMENT=production, one server for the API and the portal (see Dockerfile)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.agents import meeting_agent
from app.config import PROJECT_DIR, get_settings, secret_from_file
from app.db import init_db
from app.jobs import start_scheduler
from app.routes import (
    auth,
    data,
    emails,
    google_auth,
    health,
    llm,
    meetings,
    notifications,
    reports,
    settings,
    tasks,
)

config = get_settings()
if config.is_production and not config.login_required:
    raise RuntimeError("PORTAL_PASSWORD must be set in production (the portal needs a login).")

FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    meeting_agent.recover_unfinished()  # meetings cut off by a restart are finished now
    scheduler = start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Email & Meeting Portal API", version="1.0.0", lifespan=lifespan)


# Middleware: the last one added runs first. Order of a request:
# CORS -> login cookie (session) -> security headers -> login check -> the route.


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api") and path not in auth.PUBLIC_PATHS:
        if not auth.is_logged_in(request):
            return JSONResponse({"detail": "Please log in."}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'"
    )
    if config.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=config.session_secret or secret_from_file("session.key").decode(),
    session_cookie="portal_session",
    max_age=config.session_days * 24 * 3600,
    same_site="lax",
    https_only=config.is_production,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (
    health,
    auth,
    llm,
    emails,
    meetings,
    tasks,
    reports,
    notifications,
    data,
    google_auth,
    settings,
):
    app.include_router(module.router, prefix="/api")


# ---- The built portal (frontend/dist) --------------------------------------------------
# Every path that is not /api returns the file, or index.html so React can show the page.


@app.get("/{path:path}", include_in_schema=False)
def portal(path: str):
    if path.startswith("api/") or not (FRONTEND_DIST / "index.html").exists():
        raise HTTPException(404, "Not found.")
    file = (FRONTEND_DIST / path).resolve()
    if path and file.is_file() and file.is_relative_to(FRONTEND_DIST.resolve()):
        return FileResponse(file)
    return FileResponse(FRONTEND_DIST / "index.html")
