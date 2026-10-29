"""Query the Snowflake emulator (fakesnow) used by daily CaaS automation runs. Prints a small table.

Canned queries keep results short; every query is capped by --limit (default 20) and cells are truncated.

    python query_fakesnow.py counts --hours 24            # rows per table, latest CREATION_DATE (sink alive?)
    python query_fakesnow.py org 177 --hours 2            # rows per table for one org
    python query_fakesnow.py flow flowIddvzphcwca2        # one flow's rows across the 4 tables
    python query_fakesnow.py correlation 1961dec7-...     # rows for a correlation id
    python query_fakesnow.py record au29bpzm8qphly        # rows for a record id
    python query_fakesnow.py sql "SELECT COUNT(*) FROM MESSAGES_INBOUND_PRE"

Needs snowflake-connector-python<5 (5.x cannot log in to fakesnow). Host defaults to the nightly nginx load balancer;
use --host fakesnow.fakesnow.svc.cluster.local inside the cluster.
"""
import argparse
import json
import sys

LB_HOST = "k8s-nginxcon-nginxcon-af5d5145a7-e44fe0f367c65b89.elb.us-east-1.amazonaws.com"
PORT = 64616
TABLES = ("MESSAGES_INBOUND_PRE", "MESSAGES_INBOUND_POST", "MESSAGES_OUTBOUND_PRE", "MESSAGES_OUTBOUND_POST")
ROW_COLUMNS = "CREATION_DATE, ORG_ID, FLOW_ID, RECORD_ID, CORRELATION_ID"
CELL_WIDTH = 60


def _union(select_for_table):
    return "\nUNION ALL\n".join(select_for_table(t) for t in TABLES)


def counts_sql(hours):
    return _union(lambda t: f"SELECT '{t}' AS tbl, COUNT(*) AS total, "
                            f"CAST(SUM(CASE WHEN CREATION_DATE > DATEADD(hour, -{int(hours)}, CURRENT_TIMESTAMP()) "
                            f"THEN 1 ELSE 0 END) AS INT) AS last_{int(hours)}h, MAX(CREATION_DATE) AS latest FROM {t}")


def org_sql(org_id, hours):
    return _union(lambda t: f"SELECT '{t}' AS tbl, COUNT(*) AS n, MAX(CREATION_DATE) AS latest FROM {t} "
                            f"WHERE ORG_ID = '{_safe(org_id)}' "
                            f"AND CREATION_DATE > DATEADD(hour, -{int(hours)}, CURRENT_TIMESTAMP())")


def rows_sql(column, value):
    return _union(lambda t: f"SELECT '{t}' AS tbl, {ROW_COLUMNS} FROM {t} WHERE {column} = '{_safe(value)}'")


def _safe(value):
    if "'" in value or ";" in value:
        sys.exit(f"refusing value with quote or semicolon: {value!r}")
    return value


def build_sql(args):
    builders = {
        "counts": lambda: counts_sql(args.hours),
        "org": lambda: org_sql(args.value, args.hours),
        "flow": lambda: rows_sql("FLOW_ID", args.value),
        "correlation": lambda: rows_sql("CORRELATION_ID", args.value),
        "record": lambda: rows_sql("RECORD_ID", args.value),
        "sql": lambda: args.value,
    }
    return builders[args.query]()


def connect(host):
    import snowflake.connector
    major = int(snowflake.connector.__version__.split(".")[0])
    if major >= 5:
        sys.exit(f"snowflake-connector-python {snowflake.connector.__version__} cannot log in to fakesnow; "
                 "pip install 'snowflake-connector-python<5'")
    return snowflake.connector.connect(host=host, port=PORT, protocol="http", account="fakesnow", user="fake",
                                       password="snow", database="CAAS_MESSAGES", schema="AUTOMATION",
                                       login_timeout=20, network_timeout=60)


def run(host, sql, limit):
    with connect(host) as conn, conn.cursor() as cur:
        cur.execute(sql)
        columns = [c[0] for c in cur.description]
        return columns, cur.fetchmany(limit), cur.rowcount


def _cell(value):
    text = "" if value is None else str(value)
    return text if len(text) <= CELL_WIDTH else text[:CELL_WIDTH - 3] + "..."


def format_table(columns, rows):
    cells = [[_cell(v) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    line = lambda values: " | ".join(v.ljust(w) for v, w in zip(values, widths))
    return "\n".join([line(columns), "-+-".join("-" * w for w in widths), *(line(r) for r in cells)])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", choices=["counts", "org", "flow", "correlation", "record", "sql"])
    parser.add_argument("value", nargs="?", help="org id / flow id / correlation id / record id / SQL text")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--host", default=LB_HOST)
    parser.add_argument("--json", action="store_true", help="print JSON rows instead of a table")
    parser.add_argument("--print-sql", action="store_true", help="only print the SQL (e.g. for real Snowflake)")
    args = parser.parse_args()
    if args.query not in ("counts",) and not args.value:
        parser.error(f"{args.query} needs a value")
    sql = build_sql(args)
    if args.print_sql:
        print(sql + ";")
        return
    columns, rows, total = run(args.host, sql, args.limit)
    if args.json:
        print(json.dumps([dict(zip(columns, map(_cell, r))) for r in rows]))
    else:
        print(format_table(columns, rows))
    if total is not None and total > len(rows):
        print(f"({len(rows)} of {total} rows shown; raise --limit or narrow the query)", file=sys.stderr)


if __name__ == "__main__":
    main()
