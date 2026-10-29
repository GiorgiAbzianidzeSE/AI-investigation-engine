"""HTTP API + static UI.

Services are built once, lazily, and reached through the `get_services` dependency so tests can override
it with fakes. All errors use the body {"error": code, "detail": text}.
"""
import hmac
import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.ingest.parsers import UnsupportedFormat
from app.ingest.pipeline import DocumentExists, DocumentNotFound, IngestPipeline, ProtectedDocument
from app.investigate.agent import MODES, STRATEGIES, Investigator
from app.llm.provider import LLMUnavailable
from app.search.hybrid import strategies_for
from app.search.store import STORE_ERRORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app.api")

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 10 * 1024 * 1024
MAX_QUESTION = 500


@dataclass
class Services:
    settings: Settings
    store: object
    embedder: object
    pipeline: IngestPipeline
    llm: object | None  # None when no LLM key is configured -> /investigate answers 503
    agent: Investigator | None


def build_services(settings: Settings) -> Services:
    from app.llm.provider import LLMProvider
    from app.search.embedder import Embedder
    from app.search.hybrid import HybridSearcher
    from app.search.store import QdrantStore

    store = QdrantStore(settings)
    embedder = Embedder(settings)
    try:
        llm = LLMProvider.from_settings(settings)
    except LLMUnavailable as e:
        log.warning("LLM disabled: %s", e)
        llm = None
    searcher = HybridSearcher(store, embedder, settings)
    agent = Investigator(llm, searcher, store, settings) if llm else None
    return Services(settings, store, embedder, IngestPipeline(store, embedder, settings), llm, agent)


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = build_services(get_settings())
    return _services


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


app = FastAPI(title="AI Investigation Engine", version="0.1.0")


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


@app.exception_handler(ApiError)
def _api_error(_: Request, e: ApiError):
    return _error(e.status, e.code, e.detail)


@app.exception_handler(LLMUnavailable)
def _llm_down(_: Request, e: LLMUnavailable):
    log.error("LLM unavailable: %s", e)
    return _error(503, "llm_unavailable", "No language model is reachable right now (rate limit or outage). "
                                          "Please try again in a minute.")


def _store_down(_: Request, e: Exception):
    log.error("vector store unavailable: %s", e)
    return _error(503, "store_unavailable", "The vector database is not reachable right now.")


for _exc in STORE_ERRORS:
    app.add_exception_handler(_exc, _store_down)


@app.exception_handler(RequestValidationError)
def _invalid(_: Request, e: RequestValidationError):
    return _error(422, "invalid_request", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))


@app.exception_handler(StarletteHTTPException)
def _http(_: Request, e: StarletteHTTPException):
    return _error(e.status_code, "not_found" if e.status_code == 404 else "http_error", str(e.detail))


def require_admin(x_admin_token: str | None = Header(default=None), svc: Services = Depends(get_services)) -> None:
    expected = svc.settings.admin_token or ""
    if expected in ("", "change-me"):
        raise ApiError(401, "unauthorized", "Uploads are disabled: ADMIN_TOKEN is not configured on the server.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise ApiError(401, "unauthorized", "A valid X-Admin-Token header is required for this action "
                       "(in the UI: the Admin token field on the Documents tab; the value is the server's ADMIN_TOKEN).")


# ---------------------------------------------------------------- routes
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health(svc: Services = Depends(get_services)):
    try:
        svc.store.ping()
        qdrant, docs = "ok", svc.store.count_documents()
    except STORE_ERRORS as e:
        log.error("health: qdrant error %s", e)
        qdrant, docs = "error", None
    info = svc.embedder.query_cache_info()
    return {
        "qdrant": qdrant, "documents": docs,
        "llm_providers": list(getattr(svc.llm, "names", []) or []),
        "embed_cache": {"hits": info.hits, "misses": info.misses, "size": info.currsize, "max": info.maxsize},
    }


@app.get("/documents")
def list_documents(source: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=200),
                   offset: str | None = None, svc: Services = Depends(get_services)):
    items, nxt = svc.store.list_documents(source=source or None, q=q or None, limit=limit, offset=offset or None)
    return {"items": items, "next_offset": nxt}


@app.get("/documents/{doc_id:path}")
def get_document(doc_id: str, strategy: str = Query("b", pattern="^(a|b)$"), svc: Services = Depends(get_services)):
    doc = svc.store.get_document(doc_id)
    if doc is None:
        raise ApiError(404, "not_found", f"Unknown document {doc_id}")
    chunks = svc.store.get_chunks(doc_id, strategies_for(strategy))
    return {"document": doc, "chunks": [{"chunk_id": c.chunk_id, "heading": c.payload.get("heading"),
                                         "strategy": c.payload.get("strategy"), "text": c.text} for c in chunks]}


@app.post("/documents", dependencies=[Depends(require_admin)])
def upload_document(file: UploadFile = File(...), replace: bool = Form(False), svc: Services = Depends(get_services)):
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, "file_too_large", "Files must be at most 10 MB.")
    filename = Path(file.filename or "upload.txt").name
    try:
        r = svc.pipeline.add_file(filename, data, source="upload", replace=replace)
    except UnsupportedFormat as e:
        raise ApiError(415, "unsupported_format", str(e))
    except DocumentExists as e:
        raise ApiError(409, "already_exists", str(e))
    except ValueError as e:  # empty or unparseable file
        raise ApiError(422, "unparseable_file", str(e))
    except STORE_ERRORS:
        raise
    except Exception as e:  # noqa: BLE001 - a broken file must not become a 500
        log.exception("parse failure for %s", filename)
        raise ApiError(422, "unparseable_file", f"Could not read {filename}: {type(e).__name__}")
    return r.__dict__


@app.delete("/documents/{doc_id:path}", dependencies=[Depends(require_admin)])
def delete_document(doc_id: str, svc: Services = Depends(get_services)):
    try:
        svc.pipeline.delete(doc_id)
    except DocumentNotFound:
        raise ApiError(404, "not_found", f"Unknown document {doc_id}")
    except ProtectedDocument as e:
        raise ApiError(403, "protected", str(e))
    return {"deleted": doc_id}


class InvestigateRequest(BaseModel):
    question: str
    strategy: str | None = None
    mode: str | None = None


@app.post("/investigate")
def investigate(req: InvestigateRequest, svc: Services = Depends(get_services)):
    question = req.question.strip()
    if not question or len(question) > MAX_QUESTION:
        raise ApiError(422, "invalid_question", f"The question must be 1-{MAX_QUESTION} characters long.")
    if (req.strategy and req.strategy not in STRATEGIES) or (req.mode and req.mode not in MODES):
        raise ApiError(422, "invalid_config", f"strategy must be one of {STRATEGIES}, mode one of {MODES}")
    if svc.agent is None:
        raise LLMUnavailable("no LLM provider configured")
    return svc.agent.investigate(question, strategy=req.strategy, mode=req.mode or "full")
