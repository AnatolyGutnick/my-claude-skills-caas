import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPTS = REPO_ROOT / "skills/caas-e2e-nightly-run-troubleshooting/scripts"
sys.path.insert(0, str(SCRIPTS))
import group_failed_tests_by_error as parser  # noqa: E402
import kibana_grafana_kowl_links as links  # noqa: E402
import write_troubleshooting_report as report  # noqa: E402

BACKEND_LOG = """[2026-10-29T00:40:41.081Z] BRANCH_CAAS: master, IMAGE_MODE: latest, MODE: full
[2026-10-29T00:40:41.095Z]   caas-uploader-service=1.101.0.603
[2026-10-29T01:04:19.826Z]   Failed 04-OutboundSanity_AwsSes [11 m 5 s]
[2026-10-29T01:04:19.826Z]   Error Message:
[2026-10-29T01:04:19.826Z]    Assertion failed. Expected values to be equal.
[2026-10-29T01:04:19.826Z] The number of received report messages does not match the expected number. Report type: PreTransformer
[2026-10-29T01:04:19.826Z]   Stack Trace:
[2026-10-29T01:04:19.826Z]      at AccessFintech.Automation.CaaSTests.Outbound.CaasE2EOutbound.Outbound_Sanity(ProtocolType t) in /x.cs:line 93
[2026-10-29T01:04:19.826Z]   Standard Output Messages:
[2026-10-29T01:04:19.826Z]  2026-10-29 00:53:12.202 [INFO] BUILD_NUMBER: 4100
[2026-10-29T01:04:19.826Z]  2026-10-29 00:54:07.160 [INFO] CAAS UPLOADER TOPIC PRE-CHECK passed for topic caas_messages_automation_outbound_pre, org 154
[2026-10-29T01:04:19.826Z]  Org ID: 154
[2026-10-29T01:04:19.826Z]  Flow ID: flowIddvzphcwca2
[2026-10-29T01:04:19.826Z]  2026-10-29 01:04:14.602 [INFO] CorrelationsPerRecord: ["1961dec7-baa8-4569-9bf4-38da9a5b3ac5"]
[2026-10-29T01:04:19.826Z]  From date: 2026-10-29T00:53:09.234+00:00
[2026-10-29T01:04:19.826Z]  2026-10-29 01:04:14.401 [INFO] Outbound_Sanity CaaS SnowFlake Query :
[2026-10-29T01:04:19.826Z]  SELECT message_id
[2026-10-29T01:04:19.826Z]  FROM CAAS_MESSAGES.AUTOMATION.MESSAGES_OUTBOUND_PRE
[2026-10-29T01:04:19.826Z]  WHERE org_id = '154'
[2026-10-29T01:04:19.826Z]  2026-10-29 01:04:14.401 [INFO] Tear down SendKafkaFlow took 0.0861 ms
[2026-10-29T01:04:19.826Z]  http://caas-api-service-svc.aft-ci-4100.svc.cluster.local/graphql
[2026-10-29T01:04:19.842Z]   Skipped 01-OutboundSendToExisting
[2026-10-29T01:05:27.461Z]   Failed 05-OutboundTransferFailed [13 m]
[2026-10-29T01:05:27.461Z]   Error Message:
[2026-10-29T01:05:27.461Z]    Assertion failed. Expected collection to not be empty.
[2026-10-29T01:05:27.461Z] No messages found matching 't.Gateway.Send.180.2c9e8696a185136201a186014e640cc7' - the filter returned no expected results.
[2026-10-29T06:40:52.290Z] Total tests: Unknown
[2026-10-29T06:40:52.290Z]      Passed: 6
[2026-10-29T06:40:52.290Z]      Failed: 2
[2026-10-29T06:40:52.290Z]     Skipped: 1
"""

PLAYWRIGHT_LOG = """[2026-10-29T07:11:39.146Z]   Failed 01-E2E_FileNameFilterGlob_Sftp_Not [24 m 33 s]
[2026-10-29T07:11:39.146Z]   Error Message:
[2026-10-29T07:11:39.146Z]    Flow setup failed: Validate Pre-Transformer (2 records) - e2econn41a0fb04. Microsoft.Playwright.PlaywrightException: Locator expected not to be visible
[2026-10-29T07:11:39.146Z] Call log:
[2026-10-29T07:11:39.146Z]   - waiting for GetByText("No Rows found.")
[2026-10-29T07:11:39.146Z]   Stack Trace:
[2026-10-29T07:11:39.146Z]    at CaasPlaywright.Flows.ReportFlows.ValidatePreTransformerPlaywrightFlow.SetUpPlaywrightImplAsync()
[2026-10-29T07:21:52.944Z] Total tests: Unknown
[2026-10-29T07:21:52.944Z]      Passed: 3
[2026-10-29T07:21:52.944Z]      Failed: 1
"""


def write_log(directory, name, text):
    path = Path(directory) / name
    path.write_text(text, encoding="utf-8")
    return path


class ParseBackendLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.result = parser.parse(write_log(self.tmp.name, "node-1516-Caas_E2E_Tests.log", BACKEND_LOG))

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_every_failed_test(self):
        self.assertEqual(["04-OutboundSanity_AwsSes", "05-OutboundTransferFailed"],
                         [t["name"] for t in self.result["failed"]])

    def test_extracts_run_identifiers(self):
        first = self.result["failed"][0]
        self.assertEqual("154", first["org_id"])
        self.assertEqual("flowIddvzphcwca2", first["flow_id"])
        self.assertEqual(["1961dec7-baa8-4569-9bf4-38da9a5b3ac5"], first["correlation_ids"])
        self.assertEqual(["passed caas_messages_automation_outbound_pre"], first["prechecks"])
        self.assertEqual("Outbound_Sanity", first["test_method"])
        self.assertEqual("Caas E2E Tests", first["stage"])

    def test_extracts_printed_snowflake_query(self):
        first = self.result["failed"][0]
        self.assertEqual("2026-10-29T00:53:09.234+00:00", first["from_date"])
        self.assertEqual([{"title": "CaaS SnowFlake Query",
                           "sql": "SELECT message_id\nFROM CAAS_MESSAGES.AUTOMATION.MESSAGES_OUTBOUND_PRE\n"
                                  "WHERE org_id = '154'"}], first["snowflake_queries"])

    def test_signature_skips_generic_assertion_line(self):
        self.assertEqual("No messages found matching '<v>' - the filter returned no expected results.",
                         self.result["failed"][1]["signature"])

    def test_detects_real_snowflake_run_and_namespace(self):
        self.assertEqual("real-snowflake", self.result["snowflake_mode"])
        self.assertEqual(["aft-ci-4100"], self.result["namespaces"])
        self.assertEqual("2", self.result["counts"]["Failed"])
        self.assertEqual("1.101.0.603", self.result["versions"]["caas-uploader-service"])


class ParsePlaywrightLogTest(unittest.TestCase):
    def test_playwright_failure_is_parsed_and_ids_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = parser.parse(write_log(tmp, "node-1920-CaasE2ETests.log", PLAYWRIGHT_LOG))
        test = result["failed"][0]
        self.assertEqual("01-E2E_FileNameFilterGlob_Sftp_Not", test["name"])
        self.assertEqual("24 m 33 s", test["duration"])
        self.assertIn("<id>", test["signature"])
        self.assertNotIn("41a0fb04", test["signature"])

    def test_fakesnow_topic_means_fakesnow_mode(self):
        log = BACKEND_LOG.replace("caas_messages_automation_outbound_pre", "caas_messages_automation_fakesnow_outbound_pre")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual("fakesnow", parser.parse(write_log(tmp, "a.log", log))["snowflake_mode"])


class ReportTest(unittest.TestCase):
    def test_report_merges_stages_and_links_the_real_snowflake_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            parsed = [parser.parse(write_log(tmp, "node-1516-Caas_E2E_Tests.log", BACKEND_LOG)),
                      parser.parse(write_log(tmp, "node-1920-CaasE2ETests.log", PLAYWRIGHT_LOG)),
                      parser.parse(write_log(tmp, "node-1904-PlayWright_Tests_Short.log", PLAYWRIGHT_LOG))]
        data = report.merge(parsed)
        text = report.build_report("CaaS-EndToEnd", "4100", data)
        self.assertEqual(3, data["failed_count"])
        self.assertEqual("real-snowflake", data["snowflake_mode"])
        self.assertIn("connect-snowflake_caas_messages_automation", text)
        self.assertIn("| CaasE2ETests | 01-E2E_FileNameFilterGlob_Sftp_Not |", text)
        self.assertIn("Reports/Replay read 0 rows", text)
        self.assertIn("## ERROR log - first failed test of each group", text)
        self.assertIn("FROM CAAS_MESSAGES.AUTOMATION.MESSAGES_INBOUND_POST", text)
        self.assertIn(links.SNOWFLAKE_AUTOMATION_WORKSHEET, text)

    def test_summary_orders_sink_checks_first_and_stays_small(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = report.merge([parser.parse(write_log(tmp, "node-1516-Caas_E2E_Tests.log", BACKEND_LOG))])
        summary = report.build_summary("CaaS-EndToEnd", "4100", data, "report.md")
        self.assertEqual("reports_sink", summary["groups"][0]["cause_id"])
        self.assertEqual("connect_failed_tasks", summary["checks"][0]["id"])
        self.assertIn("snowflake_freshness", [c["id"] for c in summary["checks"]])
        self.assertNotIn("stdout_tail", summary["groups"][0]["example"])
        self.assertLess(len(report.json.dumps(summary)), 12000)

    def test_failures_json_is_slim_unless_verbose(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = report.merge([parser.parse(write_log(tmp, "node-1516-Caas_E2E_Tests.log", BACKEND_LOG))])
        self.assertNotIn("stdout_tail", report.slim(data, verbose=False)["failed"][0])
        self.assertIn("stdout_tail", report.slim(data, verbose=True)["failed"][0])

    def test_fakesnow_checks_skip_kafka_connect(self):
        checks = report.ordered_checks("fakesnow", True, "aft-ci-1", ("a", "b"), ("a", "b"), "SELECT 1")
        ids = [c["id"] for c in checks]
        self.assertEqual("sink_members", ids[0])
        self.assertNotIn("connect_failed_tasks", ids)

    def test_sinks_now_checks_cover_all_sinks_without_a_build(self):
        import mcp_checks
        checks = mcp_checks.sinks_now_checks(hours=6)
        self.assertEqual("failed_connector_tasks", checks[0]["id"])
        members = next(c for c in checks if c["id"] == "sink_members_now")
        self.assertIn("kafka_consumergroup_members", members["args"]["expr"])
        lag = next(c for c in checks if c["id"] == "sink_lag_now")
        self.assertIn('consumergroup=~"connect-.*|fakesnow-sink-0"', lag["args"]["expr"])
        trend = next(c for c in checks if c["id"] == "sink_lag_trend")
        self.assertEqual(("range", "now-6h"), (trend["args"]["queryType"], trend["args"]["startTime"]))

    def test_fakesnow_mode_links_the_emulator_sink(self):
        title, rows = report.sink_section("fakesnow", "2026-10-29T00:00:00.000Z", "now")
        self.assertIn("fakesnow", title)
        self.assertTrue(any("fakesnow-sink-0" in url for _, url in rows))


class LinksTest(unittest.TestCase):
    def test_kibana_esql_escapes_rison_quotes(self):
        url = links.kibana_esql("FROM x | WHERE a == \"it's\"", "2026-10-29T00:00:00.000Z", "now")
        self.assertIn("it!'s", url)
        self.assertTrue(url.startswith(links.KIBANA + "/app/discover#/?_g=(time:"))

    def test_grafana_explore_targets_given_datasource(self):
        url = links.grafana_explore("up", "now-1h", datasource_uid="abc")
        self.assertIn("%22uid%22%3A%22abc%22", url)


if __name__ == "__main__":
    unittest.main()
