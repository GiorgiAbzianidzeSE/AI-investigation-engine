"""Turn uploaded files into plain text + metadata.

Headings are emitted as markdown-style '# ' lines so the structure-aware chunker (strategy B)
can use them regardless of the source format.
"""
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .normalize import normalize_text

SUPPORTED = {".pdf": "pdf", ".docx": "docx", ".html": "html", ".htm": "html", ".md": "md", ".txt": "txt"}

_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_LONG_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r" (\d{1,2}), (20\d{2})\b"
)
_DOC_TYPES = [
    ("postmortem", "postmortem"), ("post-mortem", "postmortem"), ("incident", "incident"),
    ("change", "change_request"), ("changelog", "changelog"), ("runbook", "runbook"),
    ("status", "status_page"), ("finance", "report"), ("review", "report"),
    ("catalog", "service_doc"), ("architecture", "service_doc"), ("service", "service_doc"),
]


class UnsupportedFormat(ValueError):
    pass


@dataclass
class ParsedDocument:
    title: str
    text: str
    format: str
    date: str | None = None
    doc_type: str = "document"
    extra: dict = field(default_factory=dict)


def parse_file(filename: str, data: bytes) -> ParsedDocument:
    ext = Path(filename).suffix.lower()
    fmt = SUPPORTED.get(ext)
    if fmt is None:
        raise UnsupportedFormat(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED))}")
    title, text = _PARSERS[fmt](data)
    text = normalize_text(text)
    if not text:
        raise ValueError(f"No extractable text in {filename}")
    title = (title or _first_heading(text) or Path(filename).stem).strip()
    return ParsedDocument(
        title=title, text=text, format=fmt,
        date=extract_date(text), doc_type=guess_doc_type(f"{filename} {title}"),
    )


def _parse_pdf(data: bytes) -> tuple[str | None, str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    title = reader.metadata.title if reader.metadata and reader.metadata.title else None
    return title, "\n\n".join(pages)


def _parse_docx(data: bytes) -> tuple[str | None, str]:
    import docx

    document = docx.Document(io.BytesIO(data))
    lines = []
    for p in document.paragraphs:
        if not p.text.strip():
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        lines.append(f"# {p.text}" if style.startswith(("heading", "title")) else p.text)
        lines.append("")
    title = document.core_properties.title or None
    return title, "\n".join(lines)


def _parse_html(data: bytes) -> tuple[str | None, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else None
    lines = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "pre"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name.startswith("h"):
            lines += ["", f"# {txt}", ""]
        elif el.name == "li":
            lines.append(f"- {txt}")
        else:
            lines += [txt, ""]
    return title, "\n".join(lines)


def _parse_text(data: bytes) -> tuple[str | None, str]:
    return None, data.decode("utf-8", errors="replace")


_PARSERS = {"pdf": _parse_pdf, "docx": _parse_docx, "html": _parse_html, "md": _parse_text, "txt": _parse_text}


def _first_heading(text: str) -> str | None:
    for line in text.split("\n"):
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


def extract_date(text: str) -> str | None:
    if m := _ISO_DATE.search(text):
        return m.group(1)
    if m := _LONG_DATE.search(text):
        return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date().isoformat()
    return None


def guess_doc_type(name: str) -> str:
    name = name.lower()
    for key, doc_type in _DOC_TYPES:
        if key in name:
            return doc_type
    return "document"
