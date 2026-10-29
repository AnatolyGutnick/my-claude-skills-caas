# fakesnow deployment options

Three ways to run fakesnow and its Kafka sink for CaaS builds. In all three, the nightly run keeps writing to
the shared Kafka cluster and reading from real Snowflake. The full write-up with diagrams is
`infrastructure/nightly/fakesnow/snowflake/fakesnow-deployment-options.html` in `data-deploy`.

## Option 1: shared fakesnow (live)

All builds write to the shared Kafka cluster. One always-on sink loads the `_fakesnow` topics into one shared
fakesnow, which every build's Messaging and Replay read.

- Pros: simplest (no per-build pods or startup steps); proven in the POC; data stays after a build, so
  failures can be investigated later; one consumer group and one set of certs on the shared cluster.
- Cons: no isolation between builds; the sink and fakesnow are a single point of failure for every build;
  grows without limit, so it needs the scheduled purge; reached through a load balancer over plain HTTP with
  fake credentials; if fakesnow restarts empty, rerun `init_fakesnow.sql` and reset the sink's `group.id`.

## Option 2: everything per build

Non-nightly builds keep the message copies in their own Kafka and run their own sink and fakesnow. The shared
cluster is used only by the nightly run (and by Core).

- Pros: full isolation; no dependency on the shared cluster (no certs, extra topics or leftover consumer
  groups); starts empty and is deleted with the namespace; fakesnow needs no public endpoint.
- Cons: two extra pods per build, times the number of concurrent builds; startup order
  fakesnow -> `init_fakesnow.sql` -> sink -> tests; config switch for uploader topics,
  `messaging.snowflake.host` and the test framework's Snowflake Kafka consumer; data is gone after the build
  unless exported on failure.

## Option 3: Kafka shared, fakesnow per build

The shared cluster keeps all 8 topics, as in option 1. Each build adds its own sink and fakesnow, reading the
`_fakesnow` topics from the shared broker.

- Pros: broker, topics, uploader and Core stay as in option 1; each fakesnow starts empty and is deleted with
  the namespace; one build can't break, fill or restart fakesnow for others; no public endpoint.
- Cons: still no isolation (every build's sink reads all builds' messages); N sinks on the cluster Core uses,
  with one consumer group per build to delete at teardown; each namespace needs the `kowl-data-nightly` certs
  as a secret; with offset `latest` the sink must be connected before the first test sends.

## Side by side

| Aspect                    | 1 Shared (live)           | 2 Everything per build       | 3 Kafka shared, fakesnow per build |
|---------------------------|---------------------------|------------------------------|------------------------------------|
| Isolation between builds  | None                      | Full                         | None                               |
| Uses the shared cluster   | Every build               | Nightly run only             | Every build                        |
| New pods per build        | None                      | sink, fakesnow               | sink, fakesnow                     |
| Single point of failure   | Shared sink and fakesnow  | None                         | Shared broker                      |
| How fakesnow is reached   | Load balancer, plain HTTP | Inside the namespace         | Inside the namespace               |
| Leftovers after a build   | Rows in the shared tables | None                         | Consumer group on shared cluster   |
| fakesnow data after build | Kept (scheduled purge)    | Deleted                      | Deleted                            |
| Startup steps per build   | None                      | fakesnow -> init SQL -> sink | fakesnow -> init SQL -> sink       |

## When to move

- 1 -> 2: when concurrent builds start breaking each other's tests through shared rows (time- or count-based
  checks such as replay-by-filter fail first), or the shared fakesnow becomes slow or unstable under many builds.
- 2 -> 1: only if per-build pods cost too much and isolation stops mattering.
- 3 -> 2: once non-nightly builds can keep message copies in their own Kafka.

If we move to per-run instances, the current shared instance serves only the nightly run, and each run's
instance gets the build number added to its config.
