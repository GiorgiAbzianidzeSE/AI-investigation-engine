"""Our own ranking algorithm (the brief's "custom search/ranking component").

Input: two independently ranked lists (dense semantic, BM25 keyword).
Output: one list, scored by

    score = w_rrf * RRF_minmax + w_bridge * bridge + w_query * query_match

- RRF (Reciprocal Rank Fusion): sum over lists of 1 / (k + rank). Rank-based, so the two
  incomparable score scales (cosine vs BM25) never get mixed. Min-max scaled over the candidate pool.
- bridge: entities a chunk shares with chunks from *other* documents in the pool, each weighted by its
  rarity (log N/df). Multi-hop answers live in chunks that connect documents (a change id cited in an
  incident report, a person named in two Wikipedia paragraphs), so connecting chunks go up; ids that
  every summary page repeats count little.
- query_match: the query's entities found in the chunk; body match = 1, title match = 2, out of 2 each.
- diversity: at most `max_per_doc` chunks per document, so one long document can't fill the top-K.

Entities are regex-based on purpose (ids, kebab-case service names, dates, capitalized phrases): cheap,
deterministic and explainable.
"""
import math
import re
from dataclasses import dataclass, replace

from app.search.store import Hit

_ID = re.compile(r"\b[A-Z]{2,}-\d+(?:-\d+)?\b")                 # CHG-0314, INC-2041
_KEBAB = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b")                  # payments-gateway
_ISO_DATE = re.compile(r"\b20\d{2}-(\d{2}-\d{2})\b")
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]
_LONG_DATE = re.compile(r"\b(" + "|".join(m.capitalize() for m in _MONTHS) + r") (\d{1,2})\b")
_CAPS = re.compile(r"\b[A-Z][a-zA-Z0-9'&.]*(?:\s+(?:of|the|de|[A-Z][a-zA-Z0-9'&.]*))*")  # "Bank of America"
_STOP = {
    "the", "a", "an", "in", "on", "at", "it", "this", "that", "these", "those", "he", "she", "they",
    "we", "i", "what", "which", "who", "when", "where", "why", "how", "is", "was", "are", "were",
    "did", "does", "do", "and", "or", "of", "for", "to", "from", "by", "with", "as", "after", "before",
    "during", "if", "his", "her", "its", "their", "there", "both", "all", "summary", "root", "cause",
    *_MONTHS,  # "March" alone is not an entity; a full date is (see _dates)
}


@dataclass
class RankWeights:
    rrf_k: int = 60
    w_rrf: float = 1.0
    w_bridge: float = 0.3
    w_query: float = 0.2
    max_per_doc: int = 3
    bridge_pool: int = 30


_SENTENCE_START = re.compile(r"(?:^|[.!?:;|>\n-]\s*)$")


def _dates(text: str) -> set[str]:
    """Dates as a month-day key, so "March 26" in a question matches "2026-03-26" in a report."""
    keys = {f"date:{md}" for md in _ISO_DATE.findall(text)}
    keys |= {f"date:{_MONTHS.index(m.lower()) + 1:02d}-{int(d):02d}" for m, d in _LONG_DATE.findall(text)}
    return keys


def extract_entities(text: str) -> set[str]:
    ids = set(_ID.findall(text))
    ents = ids | _dates(text)
    ents |= {k for k in _KEBAB.findall(text) if not set(k.split("-")) & _STOP}  # not "end-to-end"
    rest = _ID.sub(" ", text)  # so "INC-2041" doesn't also yield the phrase "INC"
    for m in _CAPS.finditer(rest):
        words = m.group(0).strip(" .'&").split()
        # drop stop-words at the edges ("The Beatles" -> "Beatles"; "What" -> "")
        while words and words[0].lower() in _STOP:
            words = words[1:]
        while words and words[-1].lower() in _STOP:
            words = words[:-1]
        # a lone capitalized word at the start of a sentence is usually just grammar ("Because", "Every")
        if len(words) == 1 and _SENTENCE_START.search(rest[max(0, m.start() - 3):m.start()] or "\n"):
            continue
        if words and len(" ".join(words)) > 2:
            ents.add(" ".join(words))
    return {e.lower() for e in ents}


def rrf_scores(lists: list[list[Hit]], k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for hits in lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def bridge_scores(hits: list[Hit], ents: dict[str, set[str]]) -> dict[str, float]:
    """For each chunk: its entities that also occur in chunks of *other* documents, each weighted by how rare
    the entity is across the pool's documents (log N/df). An ID shared by exactly two documents is a strong
    hop signal; one mentioned by every summary page is not, so hub documents don't win by default."""
    docs_with: dict[str, set[str]] = {}
    for h in hits:
        for e in ents[h.chunk_id]:
            docs_with.setdefault(e, set()).add(h.doc_id)
    n_docs = len({h.doc_id for h in hits})
    raw = {}
    for h in hits:
        raw[h.chunk_id] = sum(math.log(1 + n_docs / len(docs_with[e]))
                              for e in ents[h.chunk_id] if len(docs_with[e] - {h.doc_id}) > 0)
    top = max(raw.values(), default=0)
    return {cid: (v / top if top else 0.0) for cid, v in raw.items()}


def query_match(query_ents: set[str], hit: Hit, hit_ents: set[str]) -> float:
    """Share of the query's entities found in the chunk, where a body match is worth 1 and a title match 2,
    out of 2 per entity: a chunk *about* the entity (title) beats one that only mentions it."""
    if not query_ents:
        return 0.0
    title = hit.title.lower()
    score = sum(2.0 if e in title else 1.0 for e in query_ents if e in hit_ents or e in title)
    return min(1.0, score / (2 * len(query_ents)))


def diversify(hits: list[Hit], max_per_doc: int) -> list[Hit]:
    seen: dict[str, int] = {}
    out = []
    for h in hits:
        if seen.get(h.doc_id, 0) < max_per_doc:
            out.append(h)
            seen[h.doc_id] = seen.get(h.doc_id, 0) + 1
    return out


def rank(query: str, dense: list[Hit], sparse: list[Hit], top_k: int,
         w: RankWeights = RankWeights(), mode: str = "full") -> list[Hit]:
    """mode: "dense" | "sparse" | "rrf" | "full" (full = RRF + bridge + query match). Used by eval to compare."""
    if mode == "dense":
        return diversify(dense, w.max_per_doc)[:top_k]
    if mode == "sparse":
        return diversify(sparse, w.max_per_doc)[:top_k]

    by_id = {h.chunk_id: h for h in [*sparse, *dense]}
    rrf = rrf_scores([dense, sparse], w.rrf_k)
    top_rrf = max(rrf.values(), default=1.0)
    ordered = sorted(by_id.values(), key=lambda h: rrf[h.chunk_id], reverse=True)

    if mode == "rrf":
        scored = [replace(h, score=rrf[h.chunk_id] / top_rrf) for h in ordered]
        return diversify(scored, w.max_per_doc)[:top_k]

    pool = ordered[: w.bridge_pool]
    ents = {h.chunk_id: extract_entities(f"{h.title}\n{h.text}") | {h.title.lower()} for h in pool}
    bridge = bridge_scores(pool, ents)
    q_ents = extract_entities(query)
    # Min-max over the pool, not divide-by-max: with k=60, rank 1 and rank 10 differ by only ~13% of the max,
    # so the [0, 1] boosts would swamp relevance (measured in eval: MRR fell below plain RRF).
    lo = min(rrf[h.chunk_id] for h in pool) if pool else 0.0
    span = (top_rrf - lo) or 1.0
    scored = []
    for h in pool:
        s = (w.w_rrf * (rrf[h.chunk_id] - lo) / span
             + w.w_bridge * bridge[h.chunk_id]
             + w.w_query * query_match(q_ents, h, ents[h.chunk_id]))
        scored.append(replace(h, score=round(s, 4)))
    scored.sort(key=lambda h: h.score, reverse=True)
    return diversify(scored, w.max_per_doc)[:top_k]
