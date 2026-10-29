# fakesnow troubleshooting

## Login fails with "Missing response field: master token"

```
ERROR Cannot reach fakesnow/Snowflake at fakesnow.fakesnow.svc.cluster.local:64616:
250001 (08001): Failed to login: Missing response field: master token
```

Cause: the Python client. The sink and cleanup pods run `python:latest` and `pip install` their dependencies at
start. `snowflake-connector-python` 5.x (from 2026-10-15, a new driver built from `snowflakedb/drivers`)
requires `masterToken` in the login response; fakesnow `0.11.18` does not return it. 4.x reads it with
`.get()`, so it works. fakesnow logs `200 OK` for the login, which makes it look healthy.

Fix: pin `snowflake-connector-python<5` in the pip install line (`fakesnow-sink/deployment.yaml`, done in
IC-6322; do the same in `fakesnow-sink/cronjob.yaml`), then restart the pod. Check the pod log for
`Successfully installed ... snowflake-connector-python-4.x`.

Upstream: fakesnow PR #451 adds `masterToken` to the login response. When a release has it, the pin can go,
but that release line requires Python 3.11+ (fakesnow 0.12.0 breaking change), so retest Messaging and Replay.

Java services (caas-messaging, Replay) use the JDBC driver, which does not need `masterToken`, so they keep
working while the sink is broken. That is why the symptom is "reads succeed, 0 rows".

## Sink stuck, no consumer group

The sink connects to fakesnow first and only then subscribes to Kafka. While the login fails it never joins
`fakesnow-sink-0`, so Kowl shows only the test framework's `Auto.CaasUploaderMessagesStore.*` groups on the
`_fakesnow` topics.

After a fix it starts from the committed offsets, or from `earliest` if none, so the backlog still on the topics
(about 7 days of retention) is loaded. It inserts batches of 1000 rows.

## fakesnow restarts empty

The database files are on the `fakesnow` PVC (`/data/CAAS_MESSAGES.db`), so a normal restart keeps the data.
If the volume is lost or replaced:

1. Run `init_fakesnow.sql` against the empty fakesnow.
2. Change the sink's `group.id` in `fakesnow-sink/configmap.yaml` (e.g. `fakesnow-sink-0` -> `fakesnow-sink-1`)
   so it reloads the topics from `earliest`; the old group's offsets would skip everything already loaded.

## fakesnow OOMKilled

fakesnow keeps every query result in `results_cache` forever, and each cached Arrow result pins several times
its size in native memory. The Deployment replaces it with a bounded cache of 20 entries at startup. If memory
grows again, check that override is still in the container command
(`fakesnow-deployment-current-causes-oom.yaml` is the old, unbounded version).

## Cleanup not running

`fakesnow-cleanup` runs daily at 20:00 UTC and deletes rows with `CREATION_DATE` older than 3 days from the 4
tables (rows with NULL `CREATION_DATE` stay). It uses the same pip install as the sink, so it breaks the same way.
Its pod log ends with a traceback on failure. Run it by hand with `--dry-run` to see what it would delete.

## Query returns 500 from fakesnow

fakesnow parses SQL with sqlglot; an unsupported or malformed statement comes back as
`Internal Server Error` with `sqlglot.errors.ParseError` in the fakesnow pod log. Example: a stray `;` before
`ORDER BY`. Fix the query, or check whether fakesnow supports that construct.
