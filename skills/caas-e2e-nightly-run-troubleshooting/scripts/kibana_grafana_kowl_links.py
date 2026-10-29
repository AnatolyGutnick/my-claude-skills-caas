"""Deep-link builders for Kibana, Grafana and Kowl (Redpanda Console) used in CaaS E2E troubleshooting."""
import json
from urllib.parse import quote

KIBANA = "https://dev-logs-es.accessfintech.com"
KIBANA_AUTOMATION_DATA_VIEW = "386b2840-0327-11f0-9d30-03f914a7426c"
GRAFANA = "https://monitor.accessfintech.com"
GRAFANA_NIGHTLY_BACKEND_UID = "ddm6b5imh30u8f"
GRAFANA_AUTOMATION_UID = "f62c1ccd-3ae6-4cd4-9b3b-6a271dc2d68b"
KOWL_DATA_NIGHTLY = "https://kowl-data-nightly.accessfintech.com"
KOWL_CAAS_NIGHTLY = "https://kowl-caas-nightly.accessfintech.com"
JENKINS = "https://jenkins.accessfintech.com"
SNOWFLAKE_TEST_ACCOUNT = "https://app.snowflake.com/accessfintech/test/"
SNOWFLAKE_AUTOMATION_WORKSHEET = (SNOWFLAKE_TEST_ACCOUNT +
                                  "#/workspaces/ws/USER%24/PUBLIC/DEFAULT%24/.migrated_worksheets/Automation.sql")

RISON_SAFE = "(),:'!"


def _rison_str(value):
    return "'" + value.replace("!", "!!").replace("'", "!'") + "'"


def _kibana_time(start, end):
    return quote(f"(time:(from:{_rison_str(start)},to:{_rison_str(end)}))", safe=RISON_SAFE)


def kibana_esql(query, start, end):
    app_state = f"(dataSource:(type:esql),query:(esql:{_rison_str(query)}))"
    return f"{KIBANA}/app/discover#/?_g={_kibana_time(start, end)}&_a={quote(app_state, safe=RISON_SAFE)}"


def kibana_kql(kql, start, end, columns=("message", "kubernetes.container.name")):
    cols = ",".join(columns)
    app_state = (
        f"(columns:!({cols}),dataSource:(dataViewId:{_rison_str(KIBANA_AUTOMATION_DATA_VIEW)},type:dataView),"
        f"query:(language:kuery,query:{_rison_str(kql)}),sort:!(!('@timestamp',asc)))"
    )
    return f"{KIBANA}/app/discover#/?_g={_kibana_time(start, end)}&_a={quote(app_state, safe=RISON_SAFE)}"


def grafana_explore(expr, start, end="now", datasource_uid=GRAFANA_NIGHTLY_BACKEND_UID):
    pane = {
        "a": {
            "datasource": datasource_uid,
            "queries": [{"refId": "A", "expr": expr, "datasource": {"type": "prometheus", "uid": datasource_uid}}],
            "range": {"from": start, "to": end},
        }
    }
    return f"{GRAFANA}/explore?schemaVersion=1&orgId=1&panes={quote(json.dumps(pane, separators=(',', ':')))}"


def kowl_group(group, host=KOWL_DATA_NIGHTLY):
    return f"{host}/groups/{quote(group)}"


def kowl_topic(topic, host=KOWL_DATA_NIGHTLY):
    return f"{host}/topics/{quote(topic)}"


def kowl_connectors(host=KOWL_DATA_NIGHTLY):
    return f"{host}/connect-clusters/kafka-connect"


def jenkins_run(job, build):
    return f"{JENKINS}/blue/organizations/jenkins/{job}/detail/{job}/{build}/pipeline"


def md_link(text, url):
    return f"[{text}]({url})"
