# My Claude skills (private)

Personal Claude Code skills and agents. Not shared through AFT-Marketplace.

`~/.claude/skills` and `~/.claude/agents` are junctions to the folders here, so Claude reads these files directly.

| Path                                          | What                                                                |
|-----------------------------------------------|---------------------------------------------------------------------|
| `skills/caas-e2e-nightly-run-troubleshooting` | Troubleshoot a failed CaaS-EndToEnd / AFT-EndToEnd run by build number |
| `skills/caas-snowflake-emulator`               | CaaS automation on the Snowflake emulator (fakesnow): runs, sink, fixes |
| `agents/caas-e2e-triage.md`                   | Haiku agent: runs that skill's checks and returns a short verdict    |

## Add a skill

Create `skills/<name>/SKILL.md` (frontmatter `name` = folder name). New sessions pick it up.

## Tests

```shell
python -m unittest discover -s tests -v
```

## Recreate the links on a new machine

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills" -Target "C:\AF\my-claude-skills\skills"
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\agents" -Target "C:\AF\my-claude-skills\agents"
```
