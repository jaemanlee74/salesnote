FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# 첨부파일은 볼륨(/data/uploads)에 둔다. 루트가 아닌 계정으로 실행한다.
RUN useradd --system --uid 10001 salesnote \
    && mkdir -p /data/uploads \
    && chown -R salesnote /data
USER salesnote

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

# DB가 뜰 때까지 기다렸다가 테이블과 기본 코드를 만든 뒤 서버를 띄운다.
CMD ["sh", "-c", "python -m app.init_db && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_WORKERS:-2} --proxy-headers --forwarded-allow-ips='*'"]
