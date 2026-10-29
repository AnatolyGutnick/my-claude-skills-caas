---
name: caas-e2e-nightly-run-troubleshooting
description: Troubleshoot a failed CaaS-EndToEnd or AFT-EndToEnd Jenkins run (nightly or daily) by build number - group the failed backend and Playwright tests by error, find the root cause (uploader, Kafka, messaging, Snowflake / fakesnow sink), give Kibana, Grafana, Kowl and Snowflake links, and open the Jira bug. Use for "nightly run failed", "CaaS-EndToEnd #4100", "all tests fail with Report type PreTransformer expected 1 actual 0", "No Rows found" in Playwright reports.
---

# CaaS E2E nightly run troubleshooting

Input: a build number, e.g. `4100`. Each run deploys its own namespace `aft-ci-<build>`.

## Nightly vs daily: only the Reports storage differs

| Run     | Jenkins job                                                                     | Reports read from  | Sink                                               |
|---------|---------------------------------------------------------------------------------|--------------------|----------------------------------------------------|
| Nightly | always `CaaS-EndToEnd` (started by `CaaS-EndToEnd-nightly`)                     | real Snowflake     | Kafka Connect `snowflake_caas_messages_automation` |
| Daily   | `CaaS-EndToEnd` (latest CaaS services) or `AFT-EndToEnd` (stable CaaS services) | Snowflake emulator | `kafka-fakesnow-sink` (`caas-snowflake-emulator`)  |

Everything else is the same. For `AFT-EndToEnd` pass `--job AFT-EndToEnd`.

## Save tokens: never read the raw Jenkins log

The console log is ~50k lines. Let the script read it; you read its summary (~2k tokens).

Fastest: delegate to the `caas-e2e-triage` agent (Haiku). It runs the steps below and returns an 8-line verdict.

## No build number? "Are the sinks OK now?"

`python scripts/check_snowflake_sinks_now.py` prints 4 checks (failed connector tasks, lag per sink group now,
lag trend, Kowl Connect page) for every Snowflake sink: CaaS Reports, Core events audit, static data, fakesnow.
Use it after an infra fix, or before a run.

## Step 1 - summary

```shell
export JENKINS_USER=<you> JENKINS_API_TOKEN=<token>        # personal Jenkins API token
python scripts/write_troubleshooting_report.py 4100 --summary
python scripts/write_troubleshooting_report.py 4100 --log-file log.txt --summary   # no token: downloaded log
```

Output dir `caas-e2e-<build>/`: `summary.json` (agents), `report.md` (people: ERROR log per group, Snowflake
queries, all links), `failures.json` (per test; `--verbose` adds stdout tails and stacks). Both the backend
"Caas E2E Tests" stage and the "PlayWright Tests" stages are collected, deduplicated and tagged by stage.

`summary.json` has `groups` (signature, count, `cause_id`, one example test with its ERROR text and test data)
and `checks`: ready-to-run queries, ordered most-likely-cause first, each with the expected result.

## Step 2 - run the checks in order, stop at the first that explains it

| `tool`      | Run with                                                        |
|-------------|-----------------------------------------------------------------|
| `promql`    | Grafana MCP `query_prometheus` with `args` as given             |
| `esql`      | `nightly-logs` Elasticsearch MCP `esql` with `args.query`       |
| `kowl`      | open the URL (Kowl Connect page shows the task state and trace) |
| `snowflake` | the SQL in the Snowflake UI (nightly) or the emulator (daily)   |

Example: in #4100 the first check, `connect_failed_tasks`, showed `snowflake_caas_messages_automation` with a
failed task, and that was the root cause. Use counts (`STATS`) and `instant` queries; don't fetch raw documents
unless a check needs a trace.

Detail per check and how to read the Snowflake results:
[references/investigation-playbook.md](references/investigation-playbook.md). Known causes and past tickets:
[references/known-causes.md](references/known-causes.md).

## Step 3 - report and open the bug

Give the root cause with start time and the links that prove it. Open the bug as in
[references/opening-the-bug.md](references/opening-the-bug.md): short human-style description, full details as
an attached `.md` (`report.md` is a good base).

## Scripts (Python 3.11 stdlib)

| Script                            | What it does                                                              |
|-----------------------------------|---------------------------------------------------------------------------|
| `write_troubleshooting_report.py` | Entry point: logs -> `summary.json`, `report.md`, `failures.json`         |
| `fetch_failed_stage_logs.py`      | Downloads every FAILED stage log via the Jenkins Blue Ocean REST API      |
| `group_failed_tests_by_error.py`  | Parses a `dotnet test` log into failed tests grouped by error             |
| `check_snowflake_sinks_now.py`    | Sink health right now, no build needed: failed tasks and lag of all sinks |
| `mcp_checks.py`                   | Builds the ordered MCP checks for the run's storage mode                  |
| `kibana_grafana_kowl_links.py`    | Kibana, Grafana, Kowl, Snowflake and Jenkins deep links                   |
