# Connecting to fakesnow

fakesnow speaks the Snowflake HTTP protocol, so any Snowflake client works with a few settings.

## Endpoints

| From                       | Host and port                                                                         |
|----------------------------|---------------------------------------------------------------------------------------|
| Inside the nightly cluster | `fakesnow.fakesnow.svc.cluster.local:64616`                                           |
| Outside (laptop, aft-ci)   | `k8s-nginxcon-nginxcon-af5d5145a7-e44fe0f367c65b89.elb.us-east-1.amazonaws.com:64616` |

The outside endpoint is an nginx load balancer, plain HTTP.

## Rules for any client

- `account=fakesnow`.
- SSL off on the client side (`ssl=off` in JDBC, `protocol=http` in Python). fakesnow has no TLS.
- Any username and password work; fakesnow doesn't check them.
- The CaaS data is in database `CAAS_MESSAGES`, schema `AUTOMATION`, tables `MESSAGES_INBOUND_PRE`,
  `MESSAGES_INBOUND_POST`, `MESSAGES_OUTBOUND_PRE`, `MESSAGES_OUTBOUND_POST`. Any other database name (e.g.
  `TEST_DB`) connects fine but is an empty database fakesnow creates on demand.

## JDBC / DBeaver

```
jdbc:snowflake://k8s-nginxcon-nginxcon-af5d5145a7-e44fe0f367c65b89.elb.us-east-1.amazonaws.com:64616/?account=fakesnow&ssl=off&db=CAAS_MESSAGES&schema=AUTOMATION
```

In DBeaver use the Snowflake driver, host and port as above, database `CAAS_MESSAGES`, username `fake`, any
password. Set `ssl=off` (and `account=fakesnow`) in the driver properties if the URL alone isn't enough.

The JDBC driver on Java 17+ needs `--add-opens=java.base/java.nio=ALL-UNNAMED` to read Arrow results, because
fakesnow always answers in Arrow. caas-messaging and Replay set it through `JDK_JAVA_OPTIONS`; for DBeaver add it
to `dbeaver.ini` under `-vmargs` if result sets fail to load.

caas-messaging appends a `/` to its JDBC URL, so its `messaging.snowflake.host` ends with `&_=` to swallow it.

## Python

```python
import snowflake.connector  # pin snowflake-connector-python<5, see troubleshooting.md

conn = snowflake.connector.connect(
    host="fakesnow.fakesnow.svc.cluster.local", port=64616, protocol="http",
    account="fakesnow", user="fake", password="snow",
    database="CAAS_MESSAGES", schema="AUTOMATION",
)
```

Use the load balancer host instead when running outside the cluster.

## Useful queries

```sql
-- rows per table for one org in the last hour
SELECT 'INBOUND_PRE' t, COUNT(*) FROM MESSAGES_INBOUND_PRE
WHERE ORG_ID = 177 AND CREATION_DATE > DATEADD(hour, -1, CURRENT_TIMESTAMP())
UNION ALL
SELECT 'OUTBOUND_PRE', COUNT(*) FROM MESSAGES_OUTBOUND_PRE
WHERE ORG_ID = 177 AND CREATION_DATE > DATEADD(hour, -1, CURRENT_TIMESTAMP());

-- one flow's messages
SELECT CREATION_DATE, SYSTEM_NAME, FLOW_ID, RECORD_ID
FROM MESSAGES_OUTBOUND_PRE
WHERE FLOW_ID = '<flowId>'
ORDER BY CREATION_DATE;
```

Keep queries simple: fakesnow translates SQL through sqlglot, and unsupported syntax comes back as a 500.
