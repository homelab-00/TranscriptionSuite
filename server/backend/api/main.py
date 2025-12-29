# Timing instrumentation - must be at very top before any imports
import time as _time

_start_time = _time.perf_counter()


def _log_time(msg: str) -> None:
    print(f"[TIMING] {_time.perf_counter() - _start_time:.3f}s - {msg}", flush=True)


_log_time("main.py module load started")

"""
Unified FastAPI application for TranscriptionSuite server.

Provides a single API serving:
- Transcription endpoints (/api/transcribe/*)
- Audio Notebook endpoints (/api/notebook/*)
- Search endpoints (/api/search/*)
- Admin endpoints (/api/admin/*)
- Health and status endpoints
"""

# Imports are placed after timing instrumentation intentionally
import asyncio  # noqa: E402
import os  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

_log_time("stdlib imports done")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

_log_time("fastapi imports done")

from server.core.token_store import get_token_store  # noqa: E402

_log_time("token_store imported")

from server.api.routes import admin, auth, health, llm, notebook, search, transcription, websocket  # noqa: E402

_log_time("routes imported")

from server.config import get_config  # noqa: E402

_log_time("config imported")

# NOTE: model_manager is imported lazily inside lifespan() to avoid
# loading heavy ML libraries (torch, faster_whisper) at module import time.
_log_time("model_manager import SKIPPED (lazy import in lifespan)")

from server.database.database import init_db  # noqa: E402

_log_time("database imported")

from server.logging import get_logger, setup_logging  # noqa: E402

_log_time("logging imported")

logger = get_logger("api")

# Check if TLS mode is enabled (requires authentication for all routes)
TLS_MODE = os.environ.get("TLS_ENABLED", "false").lower() == "true"

# Routes that don't require authentication
PUBLIC_ROUTES = {
    "/health",
    "/api/auth/login",
    "/auth",
    "/auth/",
    "/favicon.ico",
}

# Route prefixes that don't require authentication
PUBLIC_PREFIXES = (
    "/auth/",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce authentication for all routes in TLS mode.

    In TLS mode, all requests must include a valid Bearer token,
    except for public routes like /health, /auth, and /api/auth/login.
    Unauthenticated browser requests are redirected to /auth.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public routes without authentication
        if path in PUBLIC_ROUTES or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow /record from localhost without authentication
        client_host = request.client.host if request.client else None
        if (path == "/record" or path.startswith("/record/")) and client_host in ("127.0.0.1", "::1", "localhost"):
            return await call_next(request)

        # Check for valid authentication
        auth_header = request.headers.get("Authorization")

        # Check cookie-based auth for browser requests
        auth_cookie = request.cookies.get("auth_token")

        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif auth_cookie:
            token = auth_cookie

        if token:
            token_store = get_token_store()
            if token_store.validate_token(token):
                return await call_next(request)

        # For API requests, return 401
        if path.startswith("/api/") or path == "/ws":
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        # For browser requests to web pages, redirect to /auth
        # Preserve the original destination for redirect after auth
        original_url = str(request.url.path)
        if request.url.query:
            original_url += f"?{request.url.query}"

        return RedirectResponse(
            url=f"/auth?redirect={original_url}",
            status_code=302,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown."""
    # Lazy import to avoid loading torch/faster_whisper at module load time
    from server.core.model_manager import cleanup_models, get_model_manager

    # Startup
    _log_time("lifespan() started")
    logger.info("TranscriptionSuite server starting...")

    config = get_config()
    _log_time("config loaded")

    # Initialize logging
    setup_logging(config.logging)
    _log_time("logging setup complete")

    # Initialize database
    init_db()
    _log_time("database init_db() complete")
    logger.info("Database initialized")

    # Schedule backup check in background (non-blocking)
    backup_config = config.config.get("backup", {})
    backup_enabled = backup_config.get("enabled", True)

    if backup_enabled:
        from server.database.backup import run_backup_if_needed
        from server.database.database import get_data_dir, get_db_path

        backup_dir = get_data_dir() / "database" / "backups"
        max_age_hours = backup_config.get("max_age_hours", 1)
        max_backups = backup_config.get("max_backups", 3)

        # Run backup check as background task (does not block startup)
        asyncio.create_task(
            run_backup_if_needed(
                db_path=get_db_path(),
                backup_dir=backup_dir,
                max_age_hours=max_age_hours,
                max_backups=max_backups,
            )
        )
        _log_time("backup check scheduled (async)")
        logger.info(
            f"Backup check scheduled (max_age={max_age_hours}h, max_backups={max_backups})"
        )

    # Initialize token store (generates admin token on first run)
    get_token_store()
    _log_time("token store initialized")
    logger.info("Token store initialized")

    # Initialize model manager
    manager = get_model_manager(config.config)
    _log_time("model manager created")
    logger.info(f"Model manager initialized (GPU: {manager.gpu_available})")

    # Preload transcription model at startup
    logger.info("Preloading transcription model...")
    _log_time("starting model preload (GPU VRAM should spike now)...")
    manager.load_transcription_model()
    _log_time("model preload complete")

    # Store config in app state
    app.state.config = config
    app.state.model_manager = manager

    logger.info("Server startup complete")
    _log_time("lifespan startup complete")

    yield

    # Shutdown
    logger.info("Server shutting down...")
    cleanup_models()
    logger.info("Shutdown complete")


def create_app(config_path: Path | None = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        config_path: Optional path to configuration file

    Returns:
        Configured FastAPI application
    """
    # Initialize config early if path provided
    if config_path:
        get_config(config_path)

    app = FastAPI(
        title="TranscriptionSuite",
        description="Unified transcription server with Audio Notebook",
        version="0.3.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add authentication middleware in TLS mode
    if TLS_MODE:
        app.add_middleware(AuthenticationMiddleware)
        logger.info("TLS mode enabled - authentication required for all routes")

    # Include API routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(transcription.router, prefix="/api/transcribe", tags=["Transcription"])
    app.include_router(notebook.router, prefix="/api/notebook", tags=["Audio Notebook"])
    app.include_router(search.router, prefix="/api/search", tags=["Search"])
    app.include_router(llm.router, prefix="/api/llm", tags=["LLM"])
    app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
    app.include_router(websocket.router, tags=["WebSocket"])

    # Exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


def mount_frontend(app: FastAPI, frontend_path: Path, mount_path: str = "/") -> None:
    """
    Mount a frontend SPA to the application.

    Args:
        app: FastAPI application
        frontend_path: Path to the built frontend (dist directory)
        mount_path: URL path to mount at
    """
    if not frontend_path.exists():
        logger.warning(f"Frontend path not found: {frontend_path}")
        return

    # Mount assets directory
    assets_path = frontend_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    # Catch-all route for SPA
    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str) -> FileResponse:
        file_path = frontend_path / path
        if file_path.is_file():
            return FileResponse(file_path)
        # Return index.html for SPA routing
        return FileResponse(frontend_path / "index.html")

    logger.info(f"Frontend mounted from {frontend_path}")


# Create default app instance
_log_time("creating FastAPI app...")
app = create_app()
_log_time("FastAPI app created (lifespan will run when uvicorn starts)")

# Auth page HTML template
AUTH_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TranscriptionSuite - Authentication</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 1rem;
        }
        .container {
            width: 100%;
            max-width: 400px;
        }
        .card {
            background: #1e293b;
            border-radius: 1rem;
            padding: 2rem;
            border: 1px solid #334155;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .icon {
            width: 4rem;
            height: 4rem;
            background: #6366f1;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 1rem;
        }
        .icon svg {
            width: 2rem;
            height: 2rem;
            color: white;
        }
        h1 {
            color: white;
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
        }
        .subtitle {
            color: #94a3b8;
            font-size: 0.875rem;
        }
        .form-group {
            margin-bottom: 1.5rem;
        }
        label {
            display: block;
            color: #cbd5e1;
            font-size: 0.875rem;
            margin-bottom: 0.5rem;
        }
        input[type="password"] {
            width: 100%;
            padding: 0.75rem 1rem;
            background: #334155;
            border: 1px solid #475569;
            border-radius: 0.5rem;
            color: white;
            font-size: 1rem;
            transition: border-color 0.2s;
        }
        input[type="password"]:focus {
            outline: none;
            border-color: #6366f1;
        }
        input[type="password"]::placeholder {
            color: #64748b;
        }
        .error {
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid #ef4444;
            border-radius: 0.5rem;
            padding: 0.75rem;
            margin-bottom: 1rem;
            color: #fca5a5;
            font-size: 0.875rem;
            display: none;
        }
        .error.show {
            display: block;
        }
        button {
            width: 100%;
            padding: 0.75rem 1rem;
            background: #6366f1;
            border: none;
            border-radius: 0.5rem;
            color: white;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover {
            background: #4f46e5;
        }
        button:disabled {
            background: #475569;
            cursor: not-allowed;
        }
        .footer {
            text-align: center;
            margin-top: 1.5rem;
            color: #64748b;
            font-size: 0.75rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <div class="header">
                <div class="icon">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                            d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                </div>
                <h1>TranscriptionSuite</h1>
                <p class="subtitle">Enter your authentication token to continue</p>
            </div>
            <form id="authForm">
                <div id="error" class="error"></div>
                <div class="form-group">
                    <label for="token">Authentication Token</label>
                    <input type="password" id="token" name="token" placeholder="Enter your token..." required autofocus>
                </div>
                <button type="submit" id="submitBtn">Authenticate</button>
            </form>
        </div>
        <p class="footer">Contact your administrator if you don't have a token</p>
    </div>
    <script>
        const form = document.getElementById('authForm');
        const tokenInput = document.getElementById('token');
        const errorDiv = document.getElementById('error');
        const submitBtn = document.getElementById('submitBtn');
        
        // Get redirect URL from query params
        const urlParams = new URLSearchParams(window.location.search);
        const redirectUrl = urlParams.get('redirect') || '/notebook/calendar';
        
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const token = tokenInput.value.trim();
            if (!token) return;
            
            submitBtn.disabled = true;
            submitBtn.textContent = 'Authenticating...';
            errorDiv.classList.remove('show');
            
            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    // Set auth cookie
                    document.cookie = `auth_token=${token}; path=/; max-age=${30*24*60*60}; SameSite=Strict; Secure`;
                    // Redirect to original destination
                    window.location.href = redirectUrl;
                } else {
                    errorDiv.textContent = data.message || 'Invalid token';
                    errorDiv.classList.add('show');
                }
            } catch (err) {
                errorDiv.textContent = 'Authentication failed. Please try again.';
                errorDiv.classList.add('show');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Authenticate';
            }
        });
    </script>
</body>
</html>
"""


# Mount frontends in Docker environment
# Frontends are built and copied to /app/static/ during Docker build
_static_dir = Path("/app/static")
if _static_dir.exists():
    # Mount unified frontend for all UI routes
    _frontend_dir = _static_dir / "frontend"
    if _frontend_dir.exists():
        # Mount frontend assets for all routes
        _frontend_assets = _frontend_dir / "assets"
        if _frontend_assets.exists():
            app.mount(
                "/notebook/assets",
                StaticFiles(directory=str(_frontend_assets)),
                name="notebook_assets",
            )
            app.mount(
                "/record/assets", StaticFiles(directory=str(_frontend_assets)), name="record_assets"
            )
            app.mount(
                "/admin/assets", StaticFiles(directory=str(_frontend_assets)), name="admin_assets"
            )

        # Serve frontend for /notebook routes
        @app.get("/notebook", include_in_schema=False)
        @app.get("/notebook/{path:path}", include_in_schema=False)
        async def serve_notebook_ui(path: str = "") -> FileResponse:
            file_path = _frontend_dir / path
            if file_path.is_file() and not path.startswith("assets"):
                return FileResponse(file_path)
            return FileResponse(_frontend_dir / "index.html")

        # Serve frontend for /record routes
        @app.get("/record", include_in_schema=False)
        @app.get("/record/{path:path}", include_in_schema=False)
        async def serve_record_ui(path: str = "") -> FileResponse:
            file_path = _frontend_dir / path
            if file_path.is_file() and not path.startswith("assets"):
                return FileResponse(file_path)
            return FileResponse(_frontend_dir / "index.html")

        # Serve frontend for /admin routes
        @app.get("/admin", include_in_schema=False)
        @app.get("/admin/{path:path}", include_in_schema=False)
        async def serve_admin_ui(path: str = "") -> FileResponse:
            file_path = _frontend_dir / path
            if file_path.is_file() and not path.startswith("assets"):
                return FileResponse(file_path)
            return FileResponse(_frontend_dir / "index.html")

        logger.info(
            f"Unified UI frontend mounted at /notebook, /record, /admin from {_frontend_dir}"
        )


# Auth page route (served for all modes, but only required in TLS mode)
@app.get("/auth", include_in_schema=False)
@app.get("/auth/{path:path}", include_in_schema=False)
async def serve_auth_page(path: str = "") -> HTMLResponse:
    """Serve the authentication page."""
    return HTMLResponse(content=AUTH_PAGE_HTML)


# Root redirect - send to notebook calendar by default
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    icon_path = Path("/app/static/frontend/logo.svg")
    if icon_path.exists():
        return FileResponse(icon_path)
    return JSONResponse(status_code=204, content=None)


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    """Redirect root to /notebook/calendar."""
    return RedirectResponse(url="/notebook/calendar", status_code=302)


_log_time("main.py module load complete")
