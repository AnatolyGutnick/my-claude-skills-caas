---
name: caas-snowflake-emulator
description: How CaaS automation runs against the Snowflake Emulator (fakesnow) instead of real Snowflake - which runs use which, the K8s pieces (fakesnow, kafka_fakesnow_sink.py, fakesnow_cleanup.py), the config switches, schema changes, health checks and queries, and how to tell a broken sink from a real CaaS bug. Use for fakesnow, Snowflake emulator, CAAS_MESSAGES tables in automation, _fakesnow topics, or CaaS Reports/Replay returning 0 rows in a daily (non-nightly) E2E run.
---

# CaaS Snowflake Emulator (fakesnow)

CaaS tests and services read Reports/Replay data from real Snowflake (nightly) or from the Snowflake Emulator
([fakesnow](https://github.com/tekumara/fakesnow)), which runs in nightly K8s.

## Which run uses what

| Run                                                                    | Uploader topics                       | Reads from     |
|------------------------------------------------------------------------|---------------------------------------|----------------|
| Nightly: `CaaS-EndToEnd` started by `CaaS-EndToEnd-nightly`            | `caas_messages_automation_*`          | real Snowflake |
| Daily: `CaaS-EndToEnd` (latest) or `AFT-EndToEnd` (stable), `aft-ci-*` | `caas_messages_automation_fakesnow_*` | fakesnow       |

Not sure which one a run used: `python scripts/which_snowflake.py <console log>`.
How the switch works (Jenkins env vars, LD presets): [references/nightly-vs-daily.md](references/nightly-vs-daily.md).

## Data flow

```
caas-uploader -> Kafka (kafka-data-nightly) -> caas_messages_automation_fakesnow_{inbound,outbound}_{pre,post}
              -> kafka-fakesnow-sink -> fakesnow CAAS_MESSAGES.AUTOMATION.MESSAGES_* -> caas-messaging / Replay
```

| Component                  | Namespace                    | Logs (`logs-dev-k8s*`, `kubernetes.container.name`) |
|----------------------------|------------------------------|-----------------------------------------------------|
| `fakesnow` Deployment      | `fakesnow`                   | `fakesnow` - port 64616, data on a PVC              |
| `kafka-fakesnow-sink`      | `nightly-backend-kafka-data` | `sink` - consumer group `fakesnow-sink-0`           |
| `fakesnow-cleanup` CronJob | `nightly-backend-kafka-data` | `cleanup` - 20:00 UTC daily, keeps 3 days           |

Code and deploy files: `data-deploy` repo, `infrastructure/nightly/fakesnow/` and `.../fakesnow-sink/`.

## Scripts (`scripts/`)

| Script                      | What it does                                                                             |
|-----------------------------|------------------------------------------------------------------------------------------|
| `fakesnow_health_checks.py` | Ordered MCP checks (ES\|QL counts, PromQL) for sink, emulator, pods and cleanup          |
| `query_fakesnow.py`         | Canned queries against fakesnow: `counts`, `org`, `flow`, `correlation`, `record`, `sql` |
| `which_snowflake.py`        | Real Snowflake or fakesnow, from a Jenkins console log                                   |

`query_fakesnow.py` needs `snowflake-connector-python<5`; it reaches fakesnow through the nightly load balancer.
`--print-sql` prints the same SQL for real Snowflake.

## Health check: run `fakesnow_health_checks.py`, stop at the first failure

Symptom: `CAAS UPLOADER TOPIC PRE-CHECK passed` but Reports get `expected: 1 actual: 0`.

1. `sink_activity`: `inserted` > 0, `login_failed` = 0. Login failures = driver 5.x.
2. `sink_lag`: no series = the sink never joined its group.
3. `pod_restarts` / `pod_last_termination`: OOMKilled fakesnow = cache override missing.
4. `emulator_errors`, `cleanup_runs`, then `query_fakesnow.py counts` for the latest row per table.

Failures and fixes: [references/troubleshooting.md](references/troubleshooting.md).

## Token rules

- Run the scripts. Never page through raw logs; the checks return counts (`STATS`), not log lines.
- Never `KEEP message` on `sink` or `cleanup` logs: each line can be a whole `pip install` dump, thousands
  of tokens. Use `LIKE` flags + `STATS`, or `SUBSTRING(message, 1, 200)` with `LIMIT` 5.
- Grafana: `instant` queries; use a range only to find when something started, and with a coarse step (1h).
- fakesnow queries: canned ones first, always with `--limit`; never `SELECT *` (rows carry payload columns).
- Read the reference file for the failure you found, not all of them.

## Connecting, schema changes, deploying a fix

- Connecting (DBeaver, JDBC, Python): `account=fakesnow`, SSL off, any user, `CAAS_MESSAGES.AUTOMATION`.
  [references/connecting.md](references/connecting.md).
- Schema: new columns need nothing (the sink evolves the schema); changed types and removed columns need a
  migration in `init_fakesnow.sql` or a schema re-export.
- Fix: branch in `data-deploy` from `master`, change `infrastructure/nightly/fakesnow-sink/` or `.../fakesnow/`
  (update ConfigMap YAML and the `.py` together), PR to `master`. ArgoCD syncs in about 20 seconds; restart the sink pod
  for ConfigMap-only changes. [references/deploying-a-fix.md](references/deploying-a-fix.md).
- One shared fakesnow for all builds: tests must filter by their own org, flow and record ids, never by "latest N
  rows". Alternatives: [references/deployment-options.md](references/deployment-options.md).
