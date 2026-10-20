# Paper-only Trading Crew. No secrets are baked in: configure via env / .env at runtime (see .env.example).
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LIVE_ENABLED=false
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY crew ./crew
COPY web ./web
COPY config ./config
COPY fixtures ./fixtures
COPY scripts ./scripts
COPY tests ./tests
RUN useradd --uid 10001 --create-home crew && mkdir -p reports var && chown -R crew:crew /app/reports /app/var
USER crew
EXPOSE 8795
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8795/')" || exit 1
CMD ["sh", "-c", "python scripts/run_drills.py && python scripts/run_paper_day.py >/dev/null && exec uvicorn crew.api:app --host 0.0.0.0 --port 8795"]
