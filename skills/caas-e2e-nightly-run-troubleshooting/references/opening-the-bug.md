# Opening the bug

Use the `opening-jira-tickets` skill for project, fields and links. Project `IC`, type `Bug`. Fill in
Components (e.g. `DevOps` for infra, `Backend` for a service) and Reported-bug Environment (`Nightly` and/or
`Automation`). Example: [IC-6589](https://access-fintech.atlassian.net/browse/IC-6589).

## Description: short, human style

Someone should get it in 30 seconds. No stack traces, no long link lists. Four short sections:

```markdown
**What's wrong**
The nightly Kafka Connect job that copies CaaS report messages into Snowflake has stopped. Its task failed
with `No space left on device` on pod `connect-connect-0`. The pod still looks healthy, so it won't recover.

**Since when**
About 21:50 UTC on 2026-10-28, right after the Kafka broker was rolled during a node drain.

**Impact**
* CaaS-EndToEnd-nightly #4100: 100 tests failed, every Reports check got 0 rows.
* Tonight's nightly will fail the same way unless this is fixed.

**Ask**
1. Free disk space on `connect-connect-0` (or restart it), then restart the failed task.
2. Check that the sink's consumer-group lag drains to 0: [Kowl](<link>).

Full details (error trace, timeline, Grafana/Kibana/Kafka links) are in the attached `<TICKET>-...-details.md`.
```

Summary line: what broke and the visible effect, e.g. `Nightly Kafka Connect sink ... task FAILED ("No space left
on device") - all CaaS E2E Reports return 0`.

## Details: a .md file, attached

Write `<TICKET>-<short-name>-details.md` with: what happened, the error trace, a timeline table, impact, what was
ruled out (uploader, Kafka, messaging), current state, the ask, and every Kibana / Grafana / Kowl / Jenkins link.
`report.md` from `write_troubleshooting_report.py` is a good base.

Always attach it. The claude.ai Atlassian connector has no attachment tool, so use the alternative path through
the Atlassian plugin MCP:

1. `discover` "add attachment to a jira issue" -> operation `uploadAttachmentToJiraIssue` (run via `executeWrite`).
2. Phase 1: call it with `issueIdOrKey` and `filePath`. It returns an `uploadCommand` (a `curl` to Atlassian
   Media with a short-lived token).
3. Run that command in the shell; take `data.id` from its JSON output.
4. Phase 2: call it again with `issueIdOrKey` and `fileId` = that id.

If neither path works, say so and hand the user the file; never skip the attachment silently.

## After creating

Re-read the ticket: on `IC` an automation can overwrite fields right after creation (assignee, QA assignee).
Set back any field the reporter asked for, and link related tickets (e.g. the earlier occurrence) with
`createIssueLink`.
