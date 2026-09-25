FROM python:3.12-slim

WORKDIR /opt/kontekst
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    SOURCES_DIR=/sources \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=8787

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY seed-sources /opt/seed-sources
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/data", "/sources"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('HTTP_PORT','8787'))"

ENTRYPOINT ["/entrypoint.sh"]
