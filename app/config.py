from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_path: str | None = None  # embedded local Qdrant (dev only); overrides qdrant_url when set
    chunks_collection: str = "chunks"
    documents_collection: str = "documents"

    dense_model: str = "BAAI/bge-small-en-v1.5"
    dense_dim: int = 384
    sparse_model: str = "Qdrant/bm25"
    model_cache_dir: str = "models"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash,gemini-3-flash-preview,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_timeout_s: float = 45.0
    llm_max_retries: int = 2
    llm_cache_path: str | None = None  # JSON file; set in eval for free, reproducible re-runs

    admin_token: str = "change-me"

    # chunking
    chunk_words: int = 200
    chunk_overlap: int = 40
    default_strategy: str = "b"

    # retrieval / ranker
    candidates_k: int = 50
    top_k: int = 8
    rrf_k: int = 60
    w_rrf: float = 1.0
    w_bridge: float = 0.3
    w_query: float = 0.2
    max_chunks_per_doc: int = 3
    near_dup_threshold: float = 0.97

    # agent
    max_steps: int = 6
    max_evidence: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
