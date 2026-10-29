"""Print the MCP checks for "are the Snowflake sinks healthy right now?" - no build number needed.

Covers every Kafka Connect Snowflake connector in nightly-backend-kafka-data (CaaS Reports, Core events audit,
static data, ...) and the fakesnow sink: failed tasks, current lag per consumer group, and the lag trend.

    python check_snowflake_sinks_now.py            # trend over the last 3 hours
    python check_snowflake_sinks_now.py --hours 12

Run each check with the Grafana MCP (query_prometheus, args as given); open the kowl URL for task traces.
"""
import argparse
import json

from mcp_checks import sinks_now_checks


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=3, help="lag trend window")
    args = parser.parse_args()
    print(json.dumps(sinks_now_checks(args.hours), indent=1))


if __name__ == "__main__":
    main()
