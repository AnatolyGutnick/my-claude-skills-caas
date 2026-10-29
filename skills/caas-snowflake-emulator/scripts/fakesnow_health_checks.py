"""Print ordered, ready-to-run MCP checks for the fakesnow pipeline (sink -> emulator -> cleanup) as JSON.

Each check: {"id", "tool", "args", "expect"}. tool: promql (Grafana MCP query_prometheus), esql (nightly-logs
Elasticsearch MCP esql), script (run locally). All checks return counts or a few rows, never raw log pages.
Stop at the first check whose result matches a failure in its "expect".

    python fakesnow_health_checks.py                      # last 24 hours
    python fakesnow_health_checks.py --hours 6
    python fakesnow_health_checks.py --since 2026-10-28T20:00:00Z --until 2026-10-29T08:00:00Z
"""
import argparse
import json
from datetime import datetime, timedelta, timezone

NIGHTLY_BACKEND_UID = "ddm6b5imh30u8f"
SINK_NS = "nightly-backend-kafka-data"
SINK_GROUP = "fakesnow-sink-0"


def _esql(check_id, where, tail, expect):
    query = f"FROM logs-dev-k8s* | WHERE {where} {tail}"
    return {"id": check_id, "tool": "esql", "args": {"query": query}, "expect": expect}


def _promql(check_id, expr, at, expect):
    args = {"datasourceUid": NIGHTLY_BACKEND_UID, "expr": expr, "queryType": "instant", "endTime": at}
    return {"id": check_id, "tool": "promql", "args": args, "expect": expect}


def _flag(name, pattern):
    return f'{name} = CASE(message LIKE "{pattern}", 1, 0)'


def checks(since, until):
    window = f'@timestamp >= "{since}" AND @timestamp <= "{until}"'
    sink = f'{window} AND kubernetes.namespace == "{SINK_NS}" AND kubernetes.container.name == "sink"'
    emulator = f'{window} AND kubernetes.namespace == "fakesnow"'
    cleanup = f'{window} AND kubernetes.namespace == "{SINK_NS}" AND kubernetes.container.name == "cleanup"'
    flags = ", ".join([_flag("inserted", "*Inserted*rows*"), _flag("login_failed", "*master token*"),
                       _flag("unreachable", "*Cannot reach fakesnow*"), _flag("idle", "*No new records*")])
    return [
        _esql("sink_activity", sink,
              f"| EVAL {flags} | STATS inserted = SUM(inserted), login_failed = SUM(login_failed), "
              "unreachable = SUM(unreachable), idle = SUM(idle), last_seen = MAX(@timestamp)",
              "inserted > 0 and login_failed = 0. login_failed > 0 = snowflake-connector-python 5.x "
              "(troubleshooting.md); unreachable only = fakesnow down; no rows at all = sink pod not running"),
        _promql("sink_lag", f'sum by (topic) (kafka_consumergroup_lag{{namespace="{SINK_NS}", '
                            f'consumergroup="{SINK_GROUP}"}})', until,
                "low on the 4 _fakesnow topics; no series = sink never joined the group (login failing)"),
        _promql("pod_restarts", 'max by (namespace, pod) (kube_pod_container_status_restarts_total'
                                '{pod=~"fakesnow-.*|kafka-fakesnow-sink-.*"})', until,
                "stable count; rising = crash loop, then check pod_last_termination"),
        _promql("pod_last_termination", 'max by (pod, reason) (kube_pod_container_status_last_terminated_reason'
                                        '{pod=~"fakesnow-.*|kafka-fakesnow-sink-.*"})', until,
                "OOMKilled on fakesnow = results_cache override missing (troubleshooting.md)"),
        _esql("emulator_errors", emulator,
              '| EVAL server_error = CASE(message LIKE "*Internal Server Error*", 1, 0), '
              'parse_error = CASE(message LIKE "*ParseError*", 1, 0) '
              "| STATS lines = COUNT(*), server_error = SUM(server_error), parse_error = SUM(parse_error), "
              "last_seen = MAX(@timestamp)",
              "lines > 0 (alive); parse_error > 0 = a client sent SQL fakesnow cannot translate"),
        _esql("cleanup_runs", cleanup,
              '| EVAL ok = CASE(message LIKE "*total deleted*", 1, 0), failed = CASE(message LIKE "*Traceback*", 1, 0) '
              "| STATS runs_ok = SUM(ok), runs_failed = SUM(failed), last_seen = MAX(@timestamp)",
              "one ok run per day at 20:00 UTC; runs_failed > 0 = same pip/driver issue as the sink"),
        {"id": "table_freshness", "tool": "script", "args": {"command": "python query_fakesnow.py counts --hours 6"},
         "expect": "LATEST within minutes of the last test run; old LATEST with a running sink = nothing produced"},
    ]


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--since")
    parser.add_argument("--until")
    args = parser.parse_args()
    until = args.until or _iso(datetime.now(timezone.utc))
    since = args.since or _iso(datetime.fromisoformat(until.replace("Z", "+00:00")) - timedelta(hours=args.hours))
    print(json.dumps(checks(since, until), indent=1))


if __name__ == "__main__":
    main()
