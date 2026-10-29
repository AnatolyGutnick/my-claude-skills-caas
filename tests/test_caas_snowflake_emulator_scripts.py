import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills/caas-snowflake-emulator/scripts"
sys.path.insert(0, str(SCRIPTS))
import fakesnow_health_checks as health  # noqa: E402
import query_fakesnow as fakesnow  # noqa: E402
import which_snowflake as which  # noqa: E402


class Args:
    def __init__(self, query, value=None, hours=24):
        self.query, self.value, self.hours = query, value, hours


class QuerySqlTest(unittest.TestCase):
    def test_counts_covers_all_four_tables(self):
        sql = fakesnow.build_sql(Args("counts", hours=6))
        for table in fakesnow.TABLES:
            self.assertIn(f"FROM {table}", sql)
        self.assertIn("DATEADD(hour, -6", sql)

    def test_flow_query_filters_by_flow_and_avoids_select_star(self):
        sql = fakesnow.build_sql(Args("flow", "FlowIdTest-abc"))
        self.assertIn("WHERE FLOW_ID = 'FlowIdTest-abc'", sql)
        self.assertNotIn("SELECT *", sql)

    def test_rejects_values_that_could_break_out_of_the_literal(self):
        with self.assertRaises(SystemExit):
            fakesnow.build_sql(Args("record", "x'; DROP TABLE MESSAGES_INBOUND_PRE"))

    def test_table_truncates_long_cells(self):
        table = fakesnow.format_table(["A"], [["x" * 200]])
        self.assertLessEqual(max(len(line) for line in table.splitlines()), fakesnow.CELL_WIDTH)


class HealthChecksTest(unittest.TestCase):
    def setUp(self):
        self.checks = health.checks("2026-10-28T08:00:00Z", "2026-10-29T08:00:00Z")

    def test_sink_is_checked_first(self):
        self.assertEqual("sink_activity", self.checks[0]["id"])

    def test_log_checks_aggregate_instead_of_returning_messages(self):
        for check in (c for c in self.checks if c["tool"] == "esql"):
            self.assertIn("| STATS", check["args"]["query"])
            self.assertNotIn("KEEP", check["args"]["query"])

    def test_metric_checks_are_instant(self):
        for check in (c for c in self.checks if c["tool"] == "promql"):
            self.assertEqual("instant", check["args"]["queryType"])

    def test_output_is_valid_json(self):
        json.loads(json.dumps(self.checks))


class WhichSnowflakeTest(unittest.TestCase):
    def test_build_log_line_wins(self):
        lines = ["caas_messages_automation_outbound_pre",
                 "Snowflake FAKE - CAAS_SNOWFLAKE_HOST: host:64616/?account=fakesnow"]
        self.assertEqual("fakesnow", which.detect(lines)["mode"])

    def test_fakesnow_topic(self):
        self.assertEqual("fakesnow", which.detect(["topic caas_messages_automation_fakesnow_inbound_pre"])["mode"])

    def test_real_topic(self):
        self.assertEqual("real-snowflake", which.detect(["topic caas_messages_automation_outbound_pre, org 1"])["mode"])

    def test_nightly_upstream(self):
        line = 'Started by upstream project "CaaS-EndToEnd-nightly" build number 504'
        self.assertEqual("real-snowflake", which.detect([line])["mode"])

    def test_unknown(self):
        self.assertEqual("unknown", which.detect(["nothing here"])["mode"])


if __name__ == "__main__":
    unittest.main()
