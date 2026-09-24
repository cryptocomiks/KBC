FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY config ./config
COPY backend/app ./backend/app

WORKDIR /srv/backend
ENV CACHE_PATH=/data/kbc_cache.db ICIJ_DB_PATH=/data/icij_offshore_leaks.db
RUN useradd --create-home kbc && mkdir -p /data && chown kbc /data
USER kbc
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
