"""Parse a CaaS-EndToEnd `dotnet test` console log into failed tests, grouped by error signature.

Works for both the backend "Caas E2E Tests" stage and the "PlayWright Tests" stages: both print the same
`Failed <name> [duration]` / `Error Message:` / `Stack Trace:` / `Standard Output Messages:` blocks.

    python group_failed_tests_by_error.py caas-e2e-4100/node-1516-Caas_E2E_Tests.log > failures.json
"""
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

JENKINS_TS = re.compile(r"^\[(?P<ts>\d{4}-\d\d-\d\dT[\d:.]+Z)\] ?")
RESULT_LINE = re.compile(r"^\s{2}(?P<kind>Passed|Failed|Skipped) (?P<name>\S.*?)(?: \[(?P<dur>[^\]]+)\])?\s*$")
SECTION = re.compile(r"^\s{2}(Error Message|Stack Trace|Standard Output Messages|Standard Error Messages):\s*$")
SUMMARY = re.compile(r"^\s*(?P<key>Total tests|Passed|Failed|Skipped):\s*(?P<value>\S+)\s*$")
VERSION = re.compile(r"^\s{2}(?P<svc>caas-[\w-]+)=(?P<ver>[\d.]+)\s*$")
NAMESPACE = re.compile(r"\baft-ci-\d+\b")
FIELDS = {
    "org_id": re.compile(r"^\s*Org ID: (\S+)"),
    "flow_id": re.compile(r"^\s*Flow ID: (\S+)"),
    "connector": re.compile(r"^\s*Connector: (\S+)"),
    "build_number": re.compile(r"BUILD_NUMBER: (\d+)"),
}
FROM_DATE = re.compile(r"^\s*From date: (\S+)")
CORRELATIONS = re.compile(r"CorrelationsPerRecord: \[(.*)\]")
PRECHECK = re.compile(r"CAAS UPLOADER TOPIC PRE-CHECK (?P<status>passed|failed|timed out|FAILED)(?: for topic (?P<topic>[^,\s]+))?")
SNOWFLAKE_QUERY_HEADER = re.compile(r"\[INFO\] \S+ (?P<title>(?:CaaS )?SnowFlake (?:Flow Overview )?Query) :\s*$")
LOG_LINE = re.compile(r"^\s*\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ \[")
TEST_METHOD = re.compile(r"\.CaaSTests\.[\w.]+\.(?P<method>\w+)\(")
NOISE_LINES = {"", "Assertion failed. Expected values to be equal.", "Assertion failed."}


def strip_ts(line):
    match = JENKINS_TS.match(line)
    return (match.group("ts"), line[match.end():]) if match else (None, line)


def signature(error_lines):
    meaningful = [line.strip() for line in error_lines if line.strip() not in NOISE_LINES]
    specific = [line for line in meaningful if not line.startswith("Assertion failed.")]
    first = (specific or meaningful or ["(no error message)"])[0]
    first = re.sub(r"'[^']*'", "'<v>'", first)
    first = re.sub(r"\[[^\]]*\]", "[<v>]", first)
    first = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<uuid>", first)
    first = re.sub(r"\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{8,}\b", "<id>", first)
    return re.sub(r"\d+", "N", first)[:200]


def _new_test(match, ts):
    return {"name": match.group("name"), "duration": match.group("dur"), "finished_at": ts,
            "error": [], "stack": [], "stdout": [], "stderr": []}


class LogParser:
    def __init__(self):
        self.failed, self.counts, self.versions = [], {}, OrderedDict()
        self.namespaces, self.first_ts, self.last_ts = set(), None, None
        self.current, self.section = None, None

    def feed(self, raw):
        ts, line = strip_ts(raw.rstrip("\n"))
        self._track_time(ts)
        self.namespaces.update(NAMESPACE.findall(line))
        if self._header(line) or self._result(line, ts) or self._section(line):
            return
        if self.current is not None and self.section:
            self.current[self.section].append(line)

    def _track_time(self, ts):
        if ts:
            self.first_ts = self.first_ts or ts
            self.last_ts = ts

    def _header(self, line):
        version = VERSION.match(line)
        if version and self.current is None:
            self.versions[version.group("svc")] = version.group("ver")
            return True
        summary = SUMMARY.match(line)
        if summary:
            self._close()
            self.counts.setdefault(summary.group("key"), summary.group("value"))
            return True
        return False

    def _result(self, line, ts):
        match = RESULT_LINE.match(line)
        if not match:
            return False
        self._close()
        if match.group("kind") == "Failed":
            self.current = _new_test(match, ts)
        else:
            self.counts[match.group("kind") + " (listed)"] = self.counts.get(match.group("kind") + " (listed)", 0) + 1
        return True

    def _section(self, line):
        match = SECTION.match(line)
        if not match or self.current is None:
            return False
        self.section = {"Error Message": "error", "Stack Trace": "stack",
                        "Standard Output Messages": "stdout", "Standard Error Messages": "stderr"}[match.group(1)]
        return True

    def _close(self):
        if self.current is not None:
            self.failed.append(enrich(self.current))
        self.current, self.section = None, None

    def result(self):
        self._close()
        return {"window": {"start": self.first_ts, "end": self.last_ts}, "namespaces": sorted(self.namespaces),
                "snowflake_mode": snowflake_mode(self.failed),
                "counts": self.counts, "versions": self.versions, "failed_count": len(self.failed),
                "groups": group_by_signature(self.failed), "failed": self.failed}


def group_by_signature(failed):
    groups = OrderedDict()
    for test in failed:
        groups.setdefault(test["signature"], []).append(test["name"])
    return [{"signature": k, "count": len(v), "tests": v} for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]


def snowflake_mode(failed):
    topics = {check.split(" ", 1)[1] for test in failed for check in test["prechecks"] if " " in check}
    if any("_fakesnow_" in topic for topic in topics):
        return "fakesnow"
    if any(topic.startswith("caas_messages_automation_") for topic in topics):
        return "real-snowflake"
    return "unknown"


def _first(regex, lines):
    for line in lines:
        match = regex.search(line)
        if match:
            return match.group(1)
    return None


def snowflake_queries(stdout):
    queries, current = [], None
    for line in stdout:
        header = SNOWFLAKE_QUERY_HEADER.search(line)
        if header:
            current = {"title": header.group("title").strip(), "sql": []}
            queries.append(current)
        elif LOG_LINE.match(line):
            current = None
        elif current is not None:
            current["sql"].append(line[1:] if line.startswith(" ") else line)
    return [{"title": q["title"], "sql": "\n".join(q["sql"]).strip()} for q in queries if "".join(q["sql"]).strip()]


def _kibana_urls(stdout):
    return [line.strip() for line in stdout if line.strip().startswith("https://dev-logs-es.")]


def enrich(test):
    stdout = test.pop("stdout")
    stderr = test.pop("stderr")
    out = {key: _first(regex, stdout) for key, regex in FIELDS.items()}
    correlations = _first(CORRELATIONS, stdout)
    out["correlation_ids"] = re.findall(r"[0-9a-f-]{36}", correlations or "")
    out["prechecks"] = [m.group("status") + (" " + m.group("topic") if m.group("topic") else "")
                        for m in (PRECHECK.search(line) for line in stdout) if m]
    out["kibana_urls"] = _kibana_urls(stdout)
    out["snowflake_queries"] = snowflake_queries(stdout)
    out["from_date"] = _first(FROM_DATE, stdout)
    out["test_method"] = _first(TEST_METHOD, test["stack"])
    out["signature"] = signature(test["error"])
    out["error"] = "\n".join(line.rstrip() for line in test["error"]).strip()[:1500]
    out["stack_top"] = [line.strip() for line in test["stack"][:3]]
    out["stdout_tail"] = [line.rstrip() for line in stdout[-15:]]
    out["stderr_lines"] = len(stderr)
    return {**{k: test[k] for k in ("name", "duration", "finished_at")}, **out}


def stage_from_path(path):
    match = re.match(r"node-\d+-(?P<stage>.+)\.log$", Path(path).name)
    return match.group("stage").replace("_", " ") if match else Path(path).stem


def parse(path, stage=None):
    parser = LogParser()
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            parser.feed(raw)
    result = parser.result()
    result["stage"] = stage or stage_from_path(path)
    for test in result["failed"]:
        test["stage"] = result["stage"]
    return result


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    results = [dict(parse(p), log=str(Path(p))) for p in sys.argv[1:]]
    print(json.dumps(results[0] if len(results) == 1 else results, indent=2))


if __name__ == "__main__":
    main()
