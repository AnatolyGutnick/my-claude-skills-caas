"""Download the logs of the failed stages of a Jenkins pipeline run through the Blue Ocean REST API.

Auth: set JENKINS_USER and JENKINS_API_TOKEN (personal API token from Jenkins > your user > Security).

    python fetch_failed_stage_logs.py 4100
    python fetch_failed_stage_logs.py 4100 --job CaaS-EndToEnd --out ./run-4100 --node 1516
"""
import argparse
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

from kibana_grafana_kowl_links import JENKINS

BLUE = JENKINS + "/blue/rest/organizations/jenkins/pipelines/{job}/runs/{build}"


def _auth_header():
    user = os.environ.get("JENKINS_USER")
    token = os.environ.get("JENKINS_API_TOKEN")
    if not user or not token:
        sys.exit("Set JENKINS_USER and JENKINS_API_TOKEN, or download the log by hand and use --log-file.")
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


def _get(url, auth):
    request = urllib.request.Request(url, headers={"Authorization": auth})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def get_run(job, build, auth):
    return json.loads(_get(BLUE.format(job=job, build=build) + "/", auth))


def get_nodes(job, build, auth):
    return json.loads(_get(BLUE.format(job=job, build=build) + "/nodes/", auth))


def failed_nodes(nodes):
    return [n for n in nodes if n.get("result") in ("FAILURE", "UNSTABLE", "ABORTED")]


def node_log(job, build, node_id, auth):
    url = BLUE.format(job=job, build=build) + f"/nodes/{node_id}/log/?start=0"
    return _get(url, auth).decode("utf-8", errors="replace")


def _safe(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def fetch(job, build, out_dir, node_ids=None):
    auth = _auth_header()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run = get_run(job, build, auth)
    nodes = get_nodes(job, build, auth)
    chosen = [n for n in nodes if n["id"] in node_ids] if node_ids else failed_nodes(nodes)
    saved = []
    for node in chosen:
        path = out / f"node-{node['id']}-{_safe(node['displayName'])}.log"
        path.write_text(node_log(job, build, node["id"], auth), encoding="utf-8")
        saved.append({"id": node["id"], "name": node["displayName"], "result": node.get("result"), "path": str(path)})
    meta = {"job": job, "build": build, "result": run.get("result"), "startTime": run.get("startTime"),
            "causes": [c.get("shortDescription") for c in run.get("causes") or []], "logs": saved}
    (out / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("build", help="build number, e.g. 4100")
    parser.add_argument("--job", default="CaaS-EndToEnd")
    parser.add_argument("--out", default=None, help="output dir (default ./caas-e2e-<build>)")
    parser.add_argument("--node", action="append", help="only this Blue Ocean node id (repeatable)")
    args = parser.parse_args()
    meta = fetch(args.job, args.build, args.out or f"caas-e2e-{args.build}", args.node)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
