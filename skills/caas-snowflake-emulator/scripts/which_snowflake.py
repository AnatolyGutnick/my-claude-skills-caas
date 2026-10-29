"""Tell whether a CaaS automation run used real Snowflake (nightly) or the emulator (fakesnow), from its logs.

Reads Jenkins console logs (deploy or test job) and looks for, in order:
  1. "Snowflake REAL|FAKE - CAAS_SNOWFLAKE_HOST: ..." (printed by config.snowFlakeEnvSetup)
  2. uploader topics: caas_messages_automation_fakesnow_* = fakesnow, caas_messages_automation_* = real
  3. "Started by upstream project "CaaS-EndToEnd-nightly"" = real

    python which_snowflake.py ~/Downloads/log.txt
    some-command | python which_snowflake.py -
Prints one JSON line: {"mode": "real-snowflake"|"fakesnow"|"unknown", "evidence": "..."}.
"""
import json
import re
import sys

RULES = [
    (re.compile(r"Snowflake (REAL|FAKE) - CAAS_SNOWFLAKE_HOST: (\S+)"),
     lambda m: "real-snowflake" if m.group(1) == "REAL" else "fakesnow"),
    (re.compile(r"caas_messages_automation_fakesnow_\w+"), lambda m: "fakesnow"),
    (re.compile(r"caas_messages_automation_(?:inbound|outbound)_(?:pre|post)\b"), lambda m: "real-snowflake"),
    (re.compile(r'Started by upstream project "CaaS-EndToEnd-nightly"'), lambda m: "real-snowflake"),
]


def detect(lines):
    found = {}
    for line in lines:
        for index, (regex, mode) in enumerate(RULES):
            if index not in found:
                match = regex.search(line)
                if match:
                    found[index] = {"mode": mode(match), "evidence": match.group(0)[:160]}
        if 0 in found:
            break
    return found[min(found)] if found else {"mode": "unknown", "evidence": ""}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sources = [sys.stdin if p == "-" else open(p, encoding="utf-8", errors="replace") for p in sys.argv[1:]]
    lines = (line for source in sources for line in source)
    print(json.dumps(detect(lines)))


if __name__ == "__main__":
    main()
