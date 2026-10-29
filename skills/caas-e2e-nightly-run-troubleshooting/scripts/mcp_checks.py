"""Ready-to-run MCP checks for a CaaS E2E run, ordered so the likeliest cause is checked first.

Each check is a dict an agent can execute without writing its own query:
    {"id", "tool", "args", "expect"}
tool is one of: esql (nightly-logs Elasticsearch MCP), promql (Grafana MCP), kowl (open the URL / Kowl API),
snowflake (run the SQL in the Snowflake UI or the emulator - no MCP).
"""
import kibana_grafana_kowl_links as L

CONNECT_NS = "nightly-backend-kafka-data"
REAL_SINK_CONNECTOR = "snowflake_caas_messages_automation"
REAL_SINK_GROUP = "connect-" + REAL_SINK_CONNECTOR
FAKESNOW_SINK_GROUP = "fakesnow-sink-0"


def _esql(check_id, query, expect):
    return {"id": check_id, "tool": "esql", "args": {"query": query}, "expect": expect}


def _promql(check_id, expr, at, expect, datasource=L.GRAFANA_NIGHTLY_BACKEND_UID):
    args = {"datasourceUid": datasource, "expr": expr, "queryType": "instant", "endTime": at}
    return {"id": check_id, "tool": "promql", "args": args, "expect": expect}


def _window(start, end):
    return f'@timestamp >= "{start}" AND @timestamp <= "{end}"'


def real_snowflake_checks(start, end):
    return [
        _promql("connect_failed_tasks",
                f'max by (connector) (kafka_connect_worker_connector_failed_task_count{{namespace="{CONNECT_NS}"}}) > 0',
                end, f"no {REAL_SINK_CONNECTOR} series = task healthy; value 1 = task FAILED (root cause found)"),
        _members_check("sink_members", REAL_SINK_GROUP, end),
        {"id": "connect_task_trace", "tool": "kowl", "args": {"url": L.kowl_connectors()},
         "expect": f"open {REAL_SINK_CONNECTOR}: task state RUNNING; FAILED shows the error trace"},
        _promql("sink_lag", f'sum by (topic) (kafka_consumergroup_lag{{namespace="{CONNECT_NS}", '
                            f'consumergroup="{REAL_SINK_GROUP}"}})',
                end, "near 0; hundreds and growing = sink not consuming"),
        _esql("connect_log_volume",
              f'FROM logs-dev-k8s* | WHERE {_window(start, end)} AND kubernetes.namespace == "{CONNECT_NS}" '
              'AND kubernetes.container.name == "connect-connect" '
              "| STATS n = COUNT(*) BY hour = DATE_TRUNC(1 hour, @timestamp) | SORT hour",
              "about 8k per hour; a drop to ~0 marks when the worker stopped"),
        _esql("broker_rolls",
              f'FROM logs-dev-k8s* | WHERE {_window(start, end)} AND kubernetes.namespace == "kafka" '
              f'AND message LIKE "*{CONNECT_NS}*" AND message LIKE "*Rolling Pod*" | KEEP @timestamp, message | LIMIT 20',
              "rolls right before the sink stopped = trigger"),
    ]


def fakesnow_checks(start, end):
    return [
        _members_check("sink_members", FAKESNOW_SINK_GROUP, end),
        _promql("sink_lag", f'sum by (topic) (kafka_consumergroup_lag{{namespace="{CONNECT_NS}", '
                            f'consumergroup="{FAKESNOW_SINK_GROUP}"}})',
                end, "near 0; no series = sink never logged in to fakesnow"),
        _esql("fakesnow_sink_inserts",
              f'FROM logs-dev-k8s* | WHERE {_window(start, end)} AND kubernetes.namespace == "{CONNECT_NS}" '
              'AND kubernetes.container.name == "sink" '
              '| EVAL ok = CASE(message LIKE "*Inserted*rows*", 1, 0), retry = CASE(message LIKE "*Retrying*", 1, 0) '
              "| STATS inserted = SUM(ok), retries = SUM(retry)",
              "inserted > 0 and retries ~0; retries only = sink cannot reach fakesnow"),
    ]


def run_checks(ns, start, end):
    index = f"logs-automation-k8s-{ns}*"
    return [
        _esql("errors_per_service",
              f'FROM {index} | WHERE event.level.keyword == "ERROR" '
              "| STATS n = COUNT(*) BY kubernetes.container.name.keyword | SORT n DESC | LIMIT 15",
              "a service with a burst of errors near the failing tests"),
        _esql("uploader_thread_leak",
              f'FROM {index} | WHERE kubernetes.container.name.keyword == "caas-uploader-service" '
              'AND (message LIKE "*unable to create native thread*" OR message LIKE "*Future timed out*") '
              "| STATS n = COUNT(*), first_seen = MIN(@timestamp)",
              "n = 0; n > 0 = uploader thread leak from first_seen"),
        _promql("pod_restarts", f'max by (pod) (kube_pod_container_status_restarts_total{{namespace="{ns}"}}) > 0',
                end, "no series = no restarts", L.GRAFANA_AUTOMATION_UID),
    ]


SINK_GROUPS_REGEX = "connect-.*|" + FAKESNOW_SINK_GROUP


def _members_check(check_id, group_regex, at):
    return _promql(check_id,
                   f'sum by (consumergroup) (kafka_consumergroup_members{{namespace="{CONNECT_NS}", '
                   f'consumergroup=~"{group_regex}"}})',
                   at, "1 or more per group; 0 = sink not consuming (same signal as the pipeline gate, DEVOPS-4073)")


def _promql_range(check_id, expr, hours, step_seconds, expect):
    args = {"datasourceUid": L.GRAFANA_NIGHTLY_BACKEND_UID, "expr": expr, "queryType": "range",
            "startTime": f"now-{int(hours)}h", "endTime": "now", "stepSeconds": step_seconds}
    return {"id": check_id, "tool": "promql", "args": args, "expect": expect}


def sinks_now_checks(hours=3):
    return [
        _promql("failed_connector_tasks",
                f'max by (connector) (kafka_connect_worker_connector_failed_task_count{{namespace="{CONNECT_NS}"}})',
                "now", "0 for every connector; 1 = task FAILED, open the connector in Kowl for the trace"),
        _members_check("sink_members_now", SINK_GROUPS_REGEX, "now"),
        _promql("sink_lag_now",
                f'sum by (consumergroup) (kafka_consumergroup_lag{{namespace="{CONNECT_NS}", '
                f'consumergroup=~"{SINK_GROUPS_REGEX}"}})',
                "now", "near 0 (events_audit groups can sit in the low thousands while live)"),
        _promql_range("sink_lag_trend",
                      f'sum by (consumergroup) (kafka_consumergroup_lag{{namespace="{CONNECT_NS}", '
                      f'consumergroup=~"{SINK_GROUPS_REGEX}"}})',
                      hours, 1800, "flat or falling; steadily growing = that sink stopped consuming"),
        {"id": "connectors_page", "tool": "kowl", "args": {"url": L.kowl_connectors()},
         "expect": "every connector RUNNING with tasks RUNNING"},
    ]


def snowflake_check(freshness_sql):
    return {"id": "snowflake_freshness", "tool": "snowflake", "args": {"sql": freshness_sql},
            "expect": "rows_since_run_start > 0 per table; 0 = nothing loaded during the run"}


def ordered_checks(mode, sink_first, ns, run_window, sink_window, freshness_sql):
    sink = {"real-snowflake": real_snowflake_checks, "fakesnow": fakesnow_checks}
    sink_checks = (sink[mode](*sink_window) if mode in sink
                   else real_snowflake_checks(*sink_window) + fakesnow_checks(*sink_window))
    namespace_checks = run_checks(ns, *run_window)
    first, then = (sink_checks, namespace_checks) if sink_first else (namespace_checks, sink_checks)
    return first + [snowflake_check(freshness_sql)] + then
