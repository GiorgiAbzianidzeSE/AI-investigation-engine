FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Hugging Face Spaces run the container as uid 1000
RUN useradd -m -u 1000 user
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    MODEL_CACHE_DIR=/app/models PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
# bake the embedding models into the image so a cold start doesn't download them
RUN python -c "from app.config import Settings; from app.search.embedder import Embedder; Embedder(Settings(_env_file=None))" \
    && chown -R user:user /app

USER user
EXPOSE 7860
# Render injects PORT; Hugging Face Spaces expect 7860
CMD ["sh", "-c", "exec uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
