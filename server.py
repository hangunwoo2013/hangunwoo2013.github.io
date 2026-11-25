"""Single-origin production entrypoint for B-ROUTE (frontend + /api)."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api import index as api_module


@asynccontextmanager
async def lifespan(_app: FastAPI):
    api_module.init_db()
    yield


APP_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = APP_DIR / "public"
STATIC_DIR = PUBLIC_DIR if PUBLIC_DIR.is_dir() else APP_DIR

app = FastAPI(title="B-ROUTE Web", version=api_module.APP_VERSION, lifespan=lifespan)
app.mount("/api", api_module.app, name="api")

if PUBLIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="web")
else:
    # Local development serves only the intended web assets. Do not mount the
    # repository root as StaticFiles, because it contains .env and source files.
    WEB_ASSETS = {"admin.html", "manifest.json", "sw.js", "icon.svg"}

    @app.get("/", include_in_schema=False)
    async def web_index():
        return FileResponse(APP_DIR / "index.html")

    @app.get("/{asset_name}", include_in_schema=False)
    async def web_asset(asset_name: str):
        if asset_name not in WEB_ASSETS:
            raise HTTPException(404, "Not found")
        target = APP_DIR / asset_name
        if not target.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(target)
