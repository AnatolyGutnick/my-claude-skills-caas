"""Write a troubleshooting report for a CaaS-EndToEnd run: failed tests grouped by error, likely cause, and
ready-to-click Kibana / Grafana / Kowl links for the run and for the Reports (Snowflake or fakesnow) pipeline.

    python write_troubleshooting_report.py 4100                               # fetch failed-stage logs from Jenkins
    python write_troubleshooting_report.py 4100 --log-file ~/Downloads/log.txt  # use a log you downloaded
    python write_troubleshooting_report.py 4100 --log-file log.txt --summary  # compact JSON for an agent

Writes <out>/report.md (for people), <out>/summary.json (for agents: groups, likely cause, ordered MCP checks)
and <out>/failures.json (per-test data; --verbose keeps stdout tails and stacks). Default out: ./caas-e2e-<build>.
"""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import kibana_grafana_kowl_links as L
from group_failed_tests_by_error import group_by_signature, parse
from mcp_checks import FAKESNOW_SINK_GROUP, REAL_SINK_CONNECTOR, REAL_SINK_GROUP, ordered_checks

SINK_LOOKBACK_HOURS = 4
VERBOSE_ONLY_FIELDS = ("stdout_tail", "stack_top", "kibana_urls", "snowflake_queries")

KNOWN_CAUSES = [
    {
        "id": "reports_sink",
        "match": r"received report messages does not match|never contained expected RecordId|No messages found matching"
                 r"|No Rows found|Validate (Pre|Post)-Transformer",
        "cause": "Reports/Replay read 0 rows. If the UPLOADER TOPIC PRE-CHECK passed, the uploader and Kafka are fine and "
                 "the rows never reached Snowflake / fakesnow: check the Reports sink first (section below).",
    },
    {
        "id": "before_uploader_topic",
        "match": r"PRE-CHECK|did not receive|Timed out waiting",
        "cause": "Message never reached the uploader topic: check caas-uploader-service (threads, OOM, errors) and "
                 "the transformer/dispatch services in the run namespace.",
    },
    {
        "id": "test_timeout",
        "match": r"Test exceeded|timeout|Timeout",
        "cause": "Test hung or ran out of time: look at what the test was waiting for in its stdout tail.",
    },
]
UNKNOWN_CAUSE = {"id": "unknown", "cause": "Unknown pattern: read the error and stdout tail of one test, "
                                           "then its Kibana link."}


def iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def known_cause(signature, prechecks_failed):
    if prechecks_failed:
        return KNOWN_CAUSES[1]
    return next((k for k in KNOWN_CAUSES if re.search(k["match"], signature)), UNKNOWN_CAUSE)


def likely_cause(signature, prechecks_failed):
    return known_cause(signature, prechecks_failed)["cause"]


def _prechecks_failed(tests):
    return any(c.startswith(("failed", "timed out", "FAILED")) for t in tests for c in t["prechecks"])


def group_details(data):
    details = []
    for group in data["groups"]:
        tests = [t for t in data["failed"] if t["signature"] == group["signature"]]
        details.append({"group": group, "tests": tests, "cause": known_cause(group["signature"], _prechecks_failed(tests))})
    return details


def run_links(ns, start, end):
    index = f"logs-automation-k8s-{ns}*"
    errors = (f'FROM {index} | WHERE event.level.keyword IN ("ERROR", "WARN") '
              "| STATS n = COUNT(*) BY kubernetes.container.name.keyword, event.level.keyword | SORT n DESC")
    service_log = ('FROM {index} | WHERE kubernetes.container.name.keyword == "{svc}" '
                   'AND event.level.keyword IN ("ERROR", "WARN") | KEEP @timestamp, event.level.keyword, message '
                   "| SORT @timestamp ASC | LIMIT 1000")
    rows = [("Errors/warnings per service in " + ns, L.kibana_esql(errors, start, end))]
    for svc in ("caas-uploader-service", "caas-messaging-service", "caas-api-service", "caas-transformer-service"):
        rows.append((f"{svc} errors/warnings", L.kibana_esql(service_log.format(index=index, svc=svc), start, end)))
    rows += [
        ("Pod restarts in " + ns, L.grafana_explore(
            f'max by (pod) (kube_pod_container_status_restarts_total{{namespace="{ns}"}}) > 0', start, end,
            L.GRAFANA_AUTOMATION_UID)),
        ("caas-uploader thread leak (late-run 0-row reports)", L.kibana_esql(
            f'FROM {index} | WHERE kubernetes.container.name.keyword == "caas-uploader-service" '
            'AND (message LIKE "*unable to create native thread*" OR message LIKE "*Future timed out*") '
            "| STATS n = COUNT(*), first_seen = MIN(@timestamp), last_seen = MAX(@timestamp)", start, end)),
    ]
    return rows


def real_snowflake_links(start, end):
    lag = f'sum by (topic) (kafka_consumergroup_lag{{namespace="nightly-backend-kafka-data", consumergroup="{REAL_SINK_GROUP}"}})'
    connect_logs = ('FROM logs-dev-k8s* | WHERE kubernetes.namespace == "nightly-backend-kafka-data" '
                    'AND kubernetes.container.name == "connect-connect" | KEEP @timestamp, message '
                    "| SORT @timestamp DESC | LIMIT 1000")
    rolls = ('FROM logs-dev-k8s* | WHERE kubernetes.namespace == "kafka" '
             'AND message LIKE "*nightly-backend-kafka-data*" AND message LIKE "*Rolling Pod*" '
             "| KEEP @timestamp, message | SORT @timestamp ASC | LIMIT 200")
    return [
        (f"Kafka Connect connectors (open {REAL_SINK_CONNECTOR}: task state + trace)", L.kowl_connectors()),
        (f"Consumer group {REAL_SINK_GROUP} (Empty = sink not consuming)", L.kowl_group(REAL_SINK_GROUP)),
        ("Sink lag by topic", L.grafana_explore(lag, start, end)),
        ("connect-connect-0 restarts", L.grafana_explore(
            'max by (pod) (kube_pod_container_status_restarts_total{namespace="nightly-backend-kafka-data", '
            'pod="connect-connect-0"})', start, end)),
        ("connect-connect logs", L.kibana_esql(connect_logs, start, end)),
        ("Strimzi rolls of the kafka-data cluster", L.kibana_esql(rolls, start, end)),
    ]


def fakesnow_links(start, end):
    lag = f'sum by (topic) (kafka_consumergroup_lag{{namespace="nightly-backend-kafka-data", consumergroup="{FAKESNOW_SINK_GROUP}"}})'
    sink_logs = ('FROM logs-dev-k8s* | WHERE kubernetes.namespace == "nightly-backend-kafka-data" '
                 'AND kubernetes.container.name == "sink" | KEEP @timestamp, message | SORT @timestamp DESC | LIMIT 1000')
    emulator_logs = ('FROM logs-dev-k8s* | WHERE kubernetes.namespace == "fakesnow" '
                     "| KEEP @timestamp, message | SORT @timestamp DESC | LIMIT 1000")
    return [
        (f"Consumer group {FAKESNOW_SINK_GROUP} (missing = sink never logged in)", L.kowl_group(FAKESNOW_SINK_GROUP)),
        ("fakesnow sink lag by topic", L.grafana_explore(lag, start, end)),
        ("kafka-fakesnow-sink logs (healthy = 'Inserted N rows')", L.kibana_esql(sink_logs, start, end)),
        ("fakesnow emulator logs", L.kibana_esql(emulator_logs, start, end)),
    ]


def sink_section(mode, start, end):
    if mode == "real-snowflake":
        return "Real Snowflake via Kafka Connect (nightly run)", real_snowflake_links(start, end)
    if mode == "fakesnow":
        return "Snowflake emulator / fakesnow (daily and aft-ci runs)", fakesnow_links(start, end)
    both = real_snowflake_links(start, end) + fakesnow_links(start, end)
    return "Unknown which (no PRE-CHECK topic in the log) - both sinks", both


SINK_FRESHNESS_SQL = "\nUNION ALL\n".join(
    f"SELECT '{table}' AS tbl, MAX(receive_time) AS last_row, COUNT_IF(receive_time >= '{{since}}') AS rows_since_run_start\n"
    f"FROM CAAS_MESSAGES.AUTOMATION.MESSAGES_{table}"
    for table in ("OUTBOUND_PRE", "OUTBOUND_POST", "INBOUND_PRE", "INBOUND_POST")) + ";"


def _where_to_run(mode):
    if mode == "fakesnow":
        return ("Run against the Snowflake emulator (`account=fakesnow`, DBeaver/JDBC - see the "
                "`caas-snowflake-emulator` skill); the Snowflake UI only shows real Snowflake.")
    return (f"Run in the Snowflake test account: {L.md_link('Automation worksheet', L.SNOWFLAKE_AUTOMATION_WORKSHEET)} "
            f"(personal worksheet; any worksheet in {L.md_link('accessfintech/test', L.SNOWFLAKE_TEST_ACCOUNT)} works). "
            "Run one statement at a time: select it, then Ctrl+Enter.")


def _sql_block(sql):
    return ["```sql", sql, "```", ""]


def snowflake_section(data, run_start):
    lines = ["## Snowflake check", "", _where_to_run(data["snowflake_mode"]), "",
             "Is the sink loading at all? Latest row per table (no rows since the run start = sink down):", ""]
    lines += _sql_block(SINK_FRESHNESS_SQL.format(since=run_start.replace("T", " ")[:19]))
    for group in data["groups"]:
        test = next((t for t in data["failed"] if t["signature"] == group["signature"] and t["snowflake_queries"]), None)
        if test is None:
            continue
        lines += [f"Query printed by `{test['name']}` (org {test['org_id']}, flow `{test['flow_id']}`), "
                  f"for error `{group['signature'][:80]}`:", ""]
        lines += _sql_block(test["snowflake_queries"][0]["sql"])
    lines += ["0 rows while the PRE-CHECK passed = the row never reached the table. A row that is there now but was "
              "missing while the test polled = the sink was down or late at that time.", ""]
    return lines


def test_link(ns, test, run_start):
    if not test["correlation_ids"]:
        return test["kibana_urls"][0] if test["kibana_urls"] else ""
    ids = " or ".join(f'correlationId:"{c}"' for c in test["correlation_ids"])
    return L.kibana_kql(f'kubernetes.namespace:"{ns}" and ({ids})', run_start, test["finished_at"] or run_start)


def _link_list(rows):
    return [f"- {L.md_link(text, url)}" for text, url in rows]


def _stage_counts(data):
    lines = []
    for stage, counts in data.get("counts_by_stage", {}).items():
        lines.append(f"- {stage}: passed {counts.get('Passed', '?')}, failed {counts.get('Failed', '?')}, "
                     f"skipped {counts.get('Skipped', '?')}")
    return lines


def _header(job, build, data, ns):
    return [
        f"# {job} #{build} - troubleshooting report", "",
        f"- Jenkins: {L.md_link(f'{job} #{build}', L.jenkins_run(job, build))}",
        f"- Namespace: `{ns}`",
        f"- Reports storage: `{data['snowflake_mode']}`",
        f"- Log window (UTC): {data['window']['start']} -> {data['window']['end']}",
        f"- Failed tests (unique, all stages): {data['failed_count']}",
        *_stage_counts(data), "",
    ]


def _groups(data):
    lines = ["## Failures by error", "", "| Count | Error signature | Likely cause |", "|---|---|---|"]
    for group in data["groups"]:
        tests = [t for t in data["failed"] if t["signature"] == group["signature"]]
        failed_pre = any(c.startswith(("failed", "timed out", "FAILED")) for t in tests for c in t["prechecks"])
        cause = likely_cause(group["signature"], failed_pre).replace("|", "/")
        lines.append(f"| {group['count']} | `{group['signature'].replace('|', '/')}` | {cause} |")
    return lines + [""]


def _first_errors(data):
    lines = ["## ERROR log - first failed test of each group", ""]
    for group in data["groups"]:
        test = next(t for t in data["failed"] if t["signature"] == group["signature"])
        data_fields = ", ".join(f"{label} `{test[key]}`" for label, key in
                                (("org", "org_id"), ("connector", "connector"), ("flow", "flow_id"),
                                 ("from", "from_date")) if test[key])
        lines += [f"**{test['name']}** ({test.get('stage', '')}, {test['duration']}) - {data_fields or 'no test data'}, "
                  f"pre-check: {', '.join(test['prechecks']) or '-'}", "", "```", test["error"], "```", ""]
    return lines


def _tests(ns, data, run_start):
    lines = ["## Failed tests", "", "| Stage | Test | Duration | Org | Flow | Pre-check | Logs |",
             "|---|---|---|---|---|---|---|"]
    for test in data["failed"]:
        link = test_link(ns, test, run_start)
        logs = L.md_link("Kibana", link) if link else ""
        pre = ", ".join(test["prechecks"]) or "-"
        lines.append(f"| {test.get('stage', '')} | {test['name']} | {test['duration']} | {test['org_id'] or ''} | "
                     f"{test['flow_id'] or ''} | {pre} | {logs} |")
    return lines + [""]


def build_report(job, build, data):
    ns = data["namespaces"][0] if data["namespaces"] else f"aft-ci-{build}"
    start, end = iso(data["window"]["start"]), iso(data["window"]["end"])
    sink_start = fmt(start - timedelta(hours=SINK_LOOKBACK_HOURS))
    title, sink_rows = sink_section(data["snowflake_mode"], sink_start, fmt(end))
    lines = _header(job, build, data, ns) + _groups(data) + _first_errors(data)
    lines += snowflake_section(data, data["window"]["start"])
    lines += [f"## Reports pipeline: {title}", "",
              f"Window starts {SINK_LOOKBACK_HOURS}h before the run: a sink often dies before the first test.", ""]
    lines += _link_list(sink_rows) + ["", f"## Run namespace `{ns}`", ""]
    lines += _link_list(run_links(ns, fmt(start), fmt(end))) + [""]
    return "\n".join(lines + _tests(ns, data, fmt(start)))


def _example(test):
    keys = ("name", "stage", "org_id", "connector", "flow_id", "from_date", "correlation_ids", "prechecks")
    example = {k: test.get(k) for k in keys if test.get(k)}
    example["error"] = test["error"][:300]
    return example


def _windows(data):
    start, end = iso(data["window"]["start"]), iso(data["window"]["end"])
    return (fmt(start), fmt(end)), (fmt(start - timedelta(hours=SINK_LOOKBACK_HOURS)), fmt(end))


def build_summary(job, build, data, report_path):
    ns = data["namespaces"][0] if data["namespaces"] else f"aft-ci-{build}"
    details = group_details(data)
    run_window, sink_window = _windows(data)
    freshness = SINK_FRESHNESS_SQL.format(since=run_window[0].replace("T", " ")[:19])
    sink_first = bool(details) and details[0]["cause"]["id"] == "reports_sink"
    return {
        "job": job, "build": build, "namespace": ns, "reports_storage": data["snowflake_mode"],
        "window": data["window"], "failed": data["failed_count"],
        "stages": {stage: {k: c.get(k) for k in ("Passed", "Failed", "Skipped")}
                   for stage, c in data.get("counts_by_stage", {"all": data["counts"]}).items()},
        "groups": [{"count": d["group"]["count"], "signature": d["group"]["signature"],
                    "cause_id": d["cause"]["id"], "cause": d["cause"]["cause"], "example": _example(d["tests"][0])}
                   for d in details],
        "checks": ordered_checks(data["snowflake_mode"], sink_first, ns, run_window, sink_window, freshness),
        "links": {"jenkins": L.jenkins_run(job, build), "snowflake": L.SNOWFLAKE_AUTOMATION_WORKSHEET,
                  "kowl_connectors": L.kowl_connectors()},
        "report": str(report_path),
    }


def slim(data, verbose):
    if verbose:
        return data
    failed = [{k: v for k, v in t.items() if k not in VERBOSE_ONLY_FIELDS} | {"error": t["error"][:300]}
              for t in data["failed"]]
    return {**data, "failed": failed}


def _unique_tests(parsed):
    seen, unique = set(), []
    for test in (t for p in parsed for t in p["failed"]):
        key = (test["name"], test["finished_at"])
        if key not in seen:
            seen.add(key)
            unique.append(test)
    return unique


def _known_mode(parsed):
    modes = {p["snowflake_mode"] for p in parsed} - {"unknown"}
    return modes.pop() if len(modes) == 1 else ("mixed" if modes else "unknown")


def merge(parsed):
    merged = dict(parsed[0])
    merged["failed"] = _unique_tests(parsed)
    merged["groups"] = group_by_signature(merged["failed"])
    merged["failed_count"] = len(merged["failed"])
    merged["snowflake_mode"] = _known_mode(parsed)
    merged["namespaces"] = sorted({ns for p in parsed for ns in p["namespaces"]})
    merged["counts_by_stage"] = {p["stage"]: p["counts"] for p in parsed}
    merged["window"] = {"start": min(p["window"]["start"] for p in parsed if p["window"]["start"]),
                        "end": max(p["window"]["end"] for p in parsed if p["window"]["end"])}
    return merged


def collect_logs(args, out):
    if args.log_file:
        return args.log_file
    from fetch_failed_stage_logs import fetch
    meta = fetch(args.job, args.build, out)
    return [entry["path"] for entry in meta["logs"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build", help="build number, e.g. 4100")
    parser.add_argument("--job", default="CaaS-EndToEnd")
    parser.add_argument("--log-file", action="append", help="local console log (repeatable); skips Jenkins fetch")
    parser.add_argument("--out", default=None, help="output dir (default ./caas-e2e-<build>)")
    parser.add_argument("--summary", action="store_true", help="print summary.json to stdout (for agents)")
    parser.add_argument("--verbose", action="store_true", help="keep stdout tails, stacks and queries in failures.json")
    args = parser.parse_args()
    out = Path(args.out or f"caas-e2e-{args.build}")
    out.mkdir(parents=True, exist_ok=True)
    parsed = [p for p in (parse(path) for path in collect_logs(args, out)) if p["failed"] or p["window"]["start"]]
    if not parsed:
        raise SystemExit("No test results found in the given logs.")
    data = merge(parsed)
    report_path = out / "report.md"
    report_path.write_text(build_report(args.job, args.build, data), encoding="utf-8")
    summary = build_summary(args.job, args.build, data, report_path)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out / "failures.json").write_text(json.dumps(slim(data, args.verbose), indent=1), encoding="utf-8")
    if args.summary:
        print(json.dumps(summary, separators=(",", ":")))
    else:
        print(f"{data['failed_count']} failed tests, mode {data['snowflake_mode']} -> {report_path}")


if __name__ == "__main__":
    main()
