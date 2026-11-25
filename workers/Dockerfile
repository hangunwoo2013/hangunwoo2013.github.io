FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY cloud-functions/requirements.txt /app/cloud-functions/requirements.txt
RUN pip install --no-cache-dir -r /app/cloud-functions/requirements.txt \
    && groupadd --gid 10001 broute \
    && useradd --uid 10001 --gid broute --no-create-home --shell /usr/sbin/nologin broute
COPY --chown=10001:10001 cloud-functions /app/cloud-functions
COPY --chown=10001:10001 workers /app/workers
USER 10001:10001
CMD ["python", "workers/gtfs_import_worker.py"]
