FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SUPPLIER_REVIEW_DB=/data/reviews.sqlite3 \
    SUPPLIER_DESK_MODEL_CACHE=/data/models

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY supplier_agent supplier_agent
COPY streamlit_app.py ./
COPY .streamlit/config.toml .streamlit/config.toml
RUN pip install ".[all]" \
    && useradd --create-home --uid 1000 desk \
    && mkdir -p /data && chown desk:desk /data
USER desk

EXPOSE 8501
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1
CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
