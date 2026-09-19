FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

WORKDIR /srv

COPY app/ ./app/

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=3 \
    CMD python -c "import json,os,urllib.request; \
port=os.environ.get('APP_PORT','8000'); \
r=urllib.request.urlopen('http://127.0.0.1:%s/health'%port,timeout=2); \
assert json.load(r)['status']=='healthy'" || exit 1

USER nobody

CMD ["python", "-m", "app.server"]
