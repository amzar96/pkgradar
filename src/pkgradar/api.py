from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .indexes import IndexConfig, index_refs, resolve_indexes
from .scanner import scan

WEB_DIST = Path(__file__).parent / "webdist"
LOOPBACK_HOSTS = ["127.0.0.1", "localhost", "::1"]


def create_app(
    default_root: Path | None = None,
    *,
    allow_remote: bool = False,
    indexes: list[IndexConfig] | None = None,
    trust_project_indexes: bool = False,
    index_api: str = "auto",
    index_ca_bundle: str | None = None,
    index_timeout: float = 25.0,
    index_concurrency: int = 12,
    osv_include_private: bool = False,
) -> FastAPI:
    root_default = (default_root or Path.cwd()).expanduser().resolve()
    index_configs = indexes or resolve_indexes(api=index_api, ca_bundle=index_ca_bundle)
    app = FastAPI(title="pkgradar", version=__version__, docs_url="/api/docs")

    # Host validation blocks DNS-rebinding: a page on attacker.example cannot
    # make the browser talk to 127.0.0.1 while claiming to be attacker.example.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"] if allow_remote else LOOPBACK_HOSTS,
    )

    @app.middleware("http")
    async def block_cross_site(request, call_next):
        # A drive-by page can still send no-cors requests to localhost. Reject
        # browser requests that are not same-origin; curl and other non-browser
        # clients do not send Sec-Fetch-Site and keep working.
        site = request.headers.get("sec-fetch-site")
        if request.url.path.startswith("/api/") and site not in (None, "same-origin", "none"):
            return JSONResponse({"error": "cross-site request blocked"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "version": __version__, "root": str(root_default)}

    @app.get("/api/defaults")
    async def defaults() -> dict:
        return {
            "root": str(root_default),
            "cwd": str(Path.cwd()),
            "version": __version__,
            "has_web": (WEB_DIST / "index.html").exists(),
            "indexes": [ref.model_dump(mode="json") for ref in index_refs(index_configs)],
            "trust_project_indexes": trust_project_indexes,
        }

    def _root(value: str | None) -> Path:
        path = Path(value).expanduser() if value else root_default
        path = path.resolve()
        if not path.is_dir():
            raise HTTPException(status_code=400, detail=f"not a directory: {path}")
        return path

    @app.get("/api/scan")
    async def scan_stream(
        root: str | None = Query(default=None),
        offline: bool = False,
        enrich: bool = True,
        advisories: bool = True,
        deep: bool = True,
    ) -> StreamingResponse:
        target = _root(root)

        async def generator():
            queue: asyncio.Queue = asyncio.Queue()

            async def on_event(event: str, data: dict) -> None:
                await queue.put((event, data))

            async def runner() -> None:
                try:
                    result = await scan(
                        target,
                        offline=offline,
                        enrich=enrich,
                        advisories=advisories,
                        deep=deep,
                        indexes=index_configs,
                        trust_project_indexes=trust_project_indexes,
                        index_api=index_api,
                        index_ca_bundle=index_ca_bundle,
                        index_timeout=index_timeout,
                        index_concurrency=index_concurrency,
                        osv_include_private=osv_include_private,
                        on_event=on_event,
                    )
                    await queue.put(("__result__", result.model_dump(mode="json")))
                except Exception as exc:  # pragma: no cover - surfaced to the UI
                    await queue.put(("__error__", {"message": str(exc)}))

            task = asyncio.create_task(runner())
            try:
                while True:
                    event, data = await queue.get()
                    if event == "__result__":
                        break
                    if event == "__error__":
                        yield f"event: error\ndata: {json.dumps(data)}\n\n"
                        break
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
            finally:
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/scan/result")
    async def scan_result(
        root: str | None = Query(default=None),
        offline: bool = False,
        enrich: bool = True,
        advisories: bool = True,
        deep: bool = True,
    ) -> JSONResponse:
        target = _root(root)
        result = await scan(
            target,
            offline=offline,
            enrich=enrich,
            advisories=advisories,
            deep=deep,
            indexes=index_configs,
            trust_project_indexes=trust_project_indexes,
            index_api=index_api,
            index_ca_bundle=index_ca_bundle,
            index_timeout=index_timeout,
            index_concurrency=index_concurrency,
            osv_include_private=osv_include_private,
        )
        return JSONResponse(result.model_dump(mode="json"))

    if (WEB_DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:

        @app.get("/")
        async def placeholder() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "Web UI not built yet. Run `npm install && npm run build` in web/, "
                    "or use `pkgradar tui`.",
                    "api": "/api/docs",
                }
            )

    return app
