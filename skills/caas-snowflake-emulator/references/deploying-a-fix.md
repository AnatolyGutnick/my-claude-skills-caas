# Deploying a fix to fakesnow, the sink or the cleanup

Everything is GitOps: ArgoCD watches `data-deploy` `master` and auto-syncs. A merged PR is live in the cluster
within about 20 seconds (IC-6322: merged 14:49:12, new sink pod 14:49:32). There is no Jenkins job to run.

| ArgoCD app            | Folder in `data-deploy`                 | What it owns                                              |
|-----------------------|-----------------------------------------|-----------------------------------------------------------|
| `kafka-fakesnow-sink` | `infrastructure/nightly/fakesnow-sink/` | sink Deployment, `fakesnow-cleanup` CronJob, 4 ConfigMaps |
| `kafka-data-fakesnow` | `infrastructure/nightly/fakesnow/`      | `fakesnow` Deployment, Service, PVC                       |

`infrastructure/nightly/fakesnow/snowflake/` is not deployed. It holds the source copies of the scripts,
`init_fakesnow.sql`, the deployment-options doc and old experiments.

## Which file to edit

| Change                                 | Edit                                                                                  | Restart needed?                      |
|----------------------------------------|---------------------------------------------------------------------------------------|--------------------------------------|
| Sink pip deps, image, env, resources   | `fakesnow-sink/deployment.yaml`                                                       | No, the pod template change rolls it |
| Cleanup pip deps, schedule, image      | `fakesnow-sink/cronjob.yaml`                                                          | No, next scheduled run uses it       |
| Sink settings (`sink.ini`, `group.id`) | `fakesnow-sink/configmap.yaml`                                                        | **Yes**, restart the sink pod        |
| Sink code                              | `fakesnow-sink/script-configmap.yaml` and `fakesnow/snowflake/kafka_fakesnow_sink.py` | **Yes**, restart the sink pod        |
| Cleanup code                           | `fakesnow-sink/cleanup-configmap.yaml` and `fakesnow/snowflake/fakesnow_cleanup.py`   | No, next run uses it                 |
| fakesnow image, memory, server patches | `fakesnow/deployment.yaml`                                                            | No, rolls (Recreate: short outage)   |
| Table schema                           | `fakesnow/snowflake/init_fakesnow.sql`, then run it against fakesnow                  | Run the SQL by hand                  |

The code that runs is the copy inside the ConfigMap YAML; the `.py` under `snowflake/` is the readable source.
Change both in the same PR so they stay identical (today they differ only in line endings).

A ConfigMap-only change does not touch the Deployment's pod template, so ArgoCD syncs it without restarting the
sink, and the running process keeps the old code and settings. Restart the pod (ArgoCD UI: the Deployment's
Restart action, or delete the pod). Your nightly Okta_Dev account may lack that permission in
`nightly-backend-kafka-data`; ask DevOps if so.

## Steps

1. **Branch** in `data-deploy` (Bitbucket) from the latest `master`, named after the ticket, e.g.
   `IC-6588-fix-fakesnow-cleanup-5x`. Write access to the repo is needed to push; ask a repo admin if the push
   says "does not exist or you do not have access" while fetch works.
2. **Change** the file(s) from the table above. Keep the sink and cleanup pip lines in step: both pin
   `snowflake-connector-python<5`.
3. **PR to `master`** and merge. ArgoCD applies it right away.
4. **Restart** the sink pod if the change was ConfigMap-only.
5. **Check** (all in Elasticsearch `logs-dev-k8s*`, nightly-logs cluster, filter `kubernetes.pod.name`):
   - Sink: a new `kafka-fakesnow-sink-*` pod name, `Successfully installed ... snowflake-connector-python-4.x`,
     `Loading caas_messages_automation_fakesnow_* into CAAS_MESSAGES.AUTOMATION.*` for all 4 topics, then
     `Inserted N rows (0 skipped)`. No `Cannot reach fakesnow/Snowflake` loop.
   - Cleanup: after the next 20:00 UTC run, a `fakesnow-cleanup-*` pod log with the per-table delete counts and
     no traceback. Finished cleanup pods are removed, so look in Elasticsearch, not `kubectl get pods`.
   - fakesnow: pod Running with 0 restarts; its log shows `POST /session/v1/login-request ... 200 OK` from the
     sink.
   - Kowl (kowl-data-nightly): consumer group `fakesnow-sink-0` on the 4 `_fakesnow` topics with lag going
     down.
   - End to end: a non-nightly CaaS E2E run where `ValidateCaaSReport...` passes.
