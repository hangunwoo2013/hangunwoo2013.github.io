# B-ROUTE GTFS Import Worker (1.93)

The GTFS import worker is a separate trusted process from the FastAPI web/API container. In the GitHub/Cloud Run architecture, build it with:

```bash
docker build -f workers/Dockerfile -t broute-gtfs-worker .
```

The 1.93 GitHub Actions workflow builds and pushes the worker image during an approved deployment, but **does not create or execute the Cloud Run Job yet**. A later setup step must create a Cloud Run Job (or another persistent job runner), pass the required server secrets, set `--once` for a scheduler-triggered job or configure a controlled polling process, and verify concurrency/lease behavior.

## Runtime requirements

- Python 3.12
- PostgreSQL via `DATABASE_URL`
- Private Tencent COS bucket: `COS_SECRET_ID`, `COS_SECRET_KEY`, `COS_BUCKET`, `COS_REGION`; optional `COS_SESSION_TOKEN`
- Temporary disk capacity for ZIP download and validation
- Separate runtime identity with least-privilege COS access and PostgreSQL permissions

## Local execution

```bash
python workers/gtfs_import_worker.py --once
```

For SQLite-only local tests (never production):

```bash
python workers/gtfs_import_worker.py --once --allow-sqlite
```

Long-running poller:

```bash
python workers/gtfs_import_worker.py --poll-seconds 15
```

## Behavior and safety

- Queue rows remain `queued` until claimed by a worker.
- Heartbeats and processing leases are extended during long downloads/validation.
- Failed imports remain inactive; retry restarts the failed feed import rather than resuming an exact row checkpoint.
- An active feed switches only after a successful final database transaction.
- Start with one worker. Load-test PostgreSQL locking and COS behavior before increasing concurrency.
- Worker execution may cost money. Do not promise a zero monthly bill until the actual runtime, storage, requests and network limits are measured.
