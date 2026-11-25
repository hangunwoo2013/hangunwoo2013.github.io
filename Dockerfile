FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
COPY cloud-functions/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY cloud-functions/api /app/api
COPY server.py /app/server.py
RUN mkdir -p /app/public
COPY index.html admin.html manifest.json sw.js icon.svg broute-config.js /app/public/

RUN chown -R app:app /app
USER app

ENV PORT=8080
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"]
