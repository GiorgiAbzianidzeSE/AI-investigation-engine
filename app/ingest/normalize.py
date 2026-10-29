import hashlib
import re
import unicodedata

_WS = re.compile(r"[ \t\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Unicode-normalize and collapse whitespace, keeping paragraph breaks (needed by chunking B)."""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def content_hash(text: str) -> str:
    """Hash used for exact-duplicate detection; case and whitespace insensitive."""
    canon = re.sub(r"\s+", " ", normalize_text(text).lower())
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "doc"
