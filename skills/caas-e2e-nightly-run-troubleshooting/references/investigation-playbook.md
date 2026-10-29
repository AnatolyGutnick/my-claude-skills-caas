# Investigation playbook

Same order for nightly and daily runs. Only step 3 (the sink) differs: real Snowflake for nightly, the Snowflake
emulator (fakesnow) for daily - see the `caas-snowflake-emulator` skill.

Tools: `querying-logs` (Elasticsearch MCP, cluster `nightly-logs`), `querying-metrics` (Grafana MCP),
`inspecting-kafka` (Kowl). If the `accessfintech` MCP times out on connect, retry it; as a fallback, Kibana Dev Tools
in a signed-in browser accepts the same queries through `/api/console/proxy`.

## Where the logs are

| What                                | Index                                 | Filter                                                     |
|-------------------------------------|---------------------------------------|------------------------------------------------------------|
| CaaS services of the run            | `logs-automation-k8s-aft-ci-<build>*` | `kubernetes.container.name.keyword`, `event.level.keyword` |
| Kafka Connect, fakesnow sink, Kafka | `logs-dev-k8s*`                       | `kubernetes.namespace` = `nightly-backend-kafka-data`      |
| fakesnow emulator                   | `logs-dev-k8s*`                       | `kubernetes.namespace` = `fakesnow`                        |
| Strimzi operator (broker rolls)     | `logs-dev-k8s*`                       | `kubernetes.namespace` = `kafka`                           |

In `logs-dev-k8s*` the fields are plain keywords (no `.keyword`); in `logs-automation-*` use `.keyword`.

## 0. ERROR log of the failed test (always first)

Read the `Error Message` of the first failed test per group (the report shows it) and its test data block,
printed by the test before teardown:

```
Org ID: 154 / Connector: au29bpzm8qphly / Flow ID: flowIddvzphcwca2 / From date: 2026-10-29T00:53:09.234+00:00
CaaS SnowFlake Query :           SELECT ... FROM CAAS_MESSAGES.AUTOMATION.MESSAGES_OUTBOUND_PRE WHERE org_id ...
CaaS SnowFlake Flow Overview Query :   all PRE + POST rows of the flow
SnowFlake Query :                audit events (events_from_automation.audit.events_view) for the correlation id
Kibana URL :                     the correlation id in Kibana
```

## 0b. Snowflake

Run the printed `CaaS SnowFlake Query`, then the sink-freshness query from the report (latest `receive_time` per
`MESSAGES_*` table).

- Nightly (real Snowflake): [accessfintech/test](https://app.snowflake.com/accessfintech/test/), e.g. your
  personal `Automation.sql` worksheet. The worksheet runs everything up to the next `;`: select only your
  statement, then Ctrl+Enter.
- Daily (fakesnow): connect to the emulator (`account=fakesnow`), see the `caas-snowflake-emulator` skill.

Reading the result:

| Printed query  | Freshness query             | Meaning                                                   |
|----------------|-----------------------------|-----------------------------------------------------------|
| 0 rows         | no rows since the run start | sink down for the whole run                               |
| 0 rows         | recent rows exist           | this flow's row is missing: check its PRE-CHECK and topic |
| row exists now | -                           | it arrived after the test gave up: sink was down or late  |

In #4100 the rows appeared after the sink was fixed (lag drained 07:34-07:39 UTC), hours after the tests had
polled and failed.

## 1. Uploader

From the test log: every `ValidateCaaSReport...` flow first waits for its message on the uploader topic.

- `CAAS UPLOADER TOPIC PRE-CHECK passed for topic <t>` - the uploader produced the row; go to step 2.
- PRE-CHECK failed or timed out - the problem is before the sink: uploader, transformer, dispatch.

```
FROM logs-automation-k8s-aft-ci-<build>* | WHERE kubernetes.container.name.keyword == "caas-uploader-service"
  AND event.level.keyword IN ("ERROR", "WARN") | KEEP @timestamp, message | SORT @timestamp
```

Late-run only failures with `unable to create native thread` / `Future timed out` = uploader thread leak.

## 2. Kafka

- The PRE-CHECK reads the topic itself, so a passed PRE-CHECK proves the data is there.
- Sink consumer group (Kowl `kowl-data-nightly`, or Grafana `kafka_consumergroup_lag`, datasource
  `eks-nightly-backend`, namespace `nightly-backend-kafka-data`):
  - nightly: `connect-snowflake_caas_messages_automation`
  - daily: `fakesnow-sink-0`
- Lag growing from the run start and the group `Empty` (0 members) = nothing consumes, the sink is down.

## 3. Sink

Nightly (real Snowflake):

- Kowl > Connect > `snowflake_caas_messages_automation`: connector `RUNNING` with task `FAILED` is the classic
  state. The task trace has the real error (e.g. `No space left on device`). Also check
  `snowflake_automation_events_audit` on the same worker.
- `connect-connect-0` logs per 10 minutes: about 1.4k when healthy; silence = stuck worker.
- Grafana `kube_pod_container_status_restarts_total{pod="connect-connect-0"}`; the pod can stay Ready while the
  task is dead.
- Strimzi `Rolling Pod` lines for `nightly-backend-kafka-data` just before the sink stopped point to a broker roll
  (node drain) as the trigger.

Daily (fakesnow): `kafka-fakesnow-sink` logs should show `Inserted N rows`; a retry loop on the Snowflake login
means nothing is loaded. Details in the `caas-snowflake-emulator` skill.

## 4. CaaS messaging and api

caas-api-service forwards `getMetaMessageByCriteria` to caas-messaging-service
(`MessageQueryRequestService/executeMessageQueryRequest`). A 200 with `Found 0 messages` means the query worked
and the table is empty, so it points back at the sink. Search the api-service logs for the test's correlation id
(the report links it per test). Startup-only `UNKNOWN_TOPIC_OR_PARTITION` warnings in messaging are noise.

## 5. Run namespace health

- Errors/warnings per service (report link).
- Pod restarts: Grafana datasource `automation`, `kube_pod_container_status_restarts_total{namespace="aft-ci-<build>"}`.

## Playwright stages

The Playwright tests read the same Reports data through the UI. `Validate Pre-Transformer ... GetByText("No Rows
found.")` is the UI form of `expected: 1 actual: 0`, with the same root cause. A Playwright-only failure with
healthy backend Reports is a UI or test issue: open the test's trace and screenshots from the stage artifacts.
