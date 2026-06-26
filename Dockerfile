FROM python:3.12-slim

RUN useradd -m -u 1000 appuser
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .
RUN mkdir -p /app/logs /app/data /tmp/app /app/.hermes /app/assets /data/hermes \
    && chown -R appuser:appuser /app /data/hermes

USER appuser
EXPOSE 7860
ENV PYTHONUNBUFFERED=1
ENV OMP_NUM_THREADS=1
ENV DATA_DIR=/app/data

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl --fail http://localhost:7860/health || exit 1

CMD ["uvicorn", "app:create_app", "--host", "0.0.0.0", "--port", "7860"]
