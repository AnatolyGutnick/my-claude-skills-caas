# Nightly (real Snowflake) vs daily (fakesnow): how the switch works

Designed in DEVOPS-4048, implemented by DevOps in the Jenkins shared library. No production code knows about
fakesnow: the switch is Jenkins env vars, substituted into the `automation-caas` manifests at deploy time and
read by the test framework as settings overrides.

## Decision: is this the CaaS nightly run?

`config.snowFlakeEnvSetup(Boolean realSnowflake = null)` in `jenkins-shared-library`, branch `DEVOPS-275-NewCI`,
`vars/config.groovy`. With no argument it walks the whole upstream chain:

```groovy
realSnowflake = misc.upstreamBuildJobChain().contains("CaaS-EndToEnd-nightly")
```

The whole chain matters because nightly is indirect: `CaaS-EndToEnd-nightly` -> `CaaS-EndToEnd` ->
`AFT-EndToEnd` / `AFT-EndToEnd-DeployCaasServices`. Anything else (daily, manual, `aft-ci-*`) gets fakesnow.

| Env var                            | Nightly (real)                              | Other runs (fakesnow)                            |
|------------------------------------|---------------------------------------------|--------------------------------------------------|
| `CAAS_SNOWFLAKE_HOST`              | `accessfintech-test.snowflakecomputing.com` | `<nginx ELB>:64616/?account=fakesnow&ssl=off&_=` |
| `CAAS_SNOWFLAKE_TOPIC_INFIX`       | `""`                                        | `_fakesnow`                                      |
| `Settings__CaaSSnowflakeDbAccount` | not set (appsettings)                       | `fakesnow`                                       |
| `Settings__CaaSSnowflakeDbHost`    | not set (appsettings)                       | `<nginx ELB>`                                    |
| `Settings__CaaSSnowflakeDbPort`    | not set (default 443)                       | `64616`                                          |
| `Settings__CaaSSnowflakeDbScheme`  | not set (default https)                     | `http`                                           |
| `Settings__CaasUploaderTopicInfix` | not set (appsettings)                       | `_fakesnow`                                      |

`&_=` at the end of the host swallows the `/` caas-messaging appends to its JDBC URL. The function echoes
`Snowflake REAL|FAKE - CAAS_SNOWFLAKE_HOST: ...` in the build log, which is the quickest way to see which mode a
run used.

## Where it is called

1. **Deploy job** (`AFT-EndToEnd-DeployCaasServices`, `automation-caas/.jenkins/Jenkinsfile`, before
   `deployServices()`): `config.snowFlakeEnvSetup()`. The deploy step runs the manifests through `envsubst`
   (same mechanism as `aft-ci-${BUILD_NUMBER}`), so every `${VAR}` must always be set; that is why the nightly
   branch sets the infix to `""` rather than leaving it unset.
2. **Test job** (`AFT-EndToEnd`, `automation/AccessFintech.Automation/.jenkins/AFT-EndToEnd.Jenkinsfile`):
   `config.snowFlakeEnvSetup() // temporary, it will be part of e2e configs.` The `Settings__*` vars override
   appsettings in the test process (.NET `__` = `:`).

## What consumes it

`automation-caas` manifests:

```yaml
# caas-messaging-service/latest/cm.yaml
messaging.snowflake.host: ${CAAS_SNOWFLAKE_HOST}
# caas-uploader-service/latest/cm.yaml (same for inbound-post, outbound-pre, outbound-post)
kafka.snowflake.topic.inbound-pre: caas_messages_automation${CAAS_SNOWFLAKE_TOPIC_INFIX}_inbound_pre
```

Also in `automation-caas`, independent of the mode: messaging `JDK_JAVA_OPTIONS` and
`messaging.snowflake.jdk-java-options` (for Replay jobs) set `--add-opens=java.base/java.nio=ALL-UNNAMED`, which
the JDBC driver needs to read fakesnow's Arrow results.

Test framework (`automation` repo):

- `Settings:CaasUploaderTopicInfix` picks the topics the uploader pre-check (`CaasUploaderMessagesStore`)
  consumes.
- `Settings:CaaSSnowflakeDb*` point the optional direct Snowflake check (`CaaSVerifySnowflakeUploadDirectly`,
  off by default) at fakesnow.

## The other nightly switch: storage LaunchDarkly flags

Separate from the Snowflake target. `AFT-EndToEnd.Jenkinsfile` sets
`env.isCaaSNightlyRun = (misc.upstreamBuildJob() == "CaaS-EndToEnd-nightly")`, and
`MessagingStorageFlagDefaults.BaselineFallthrough` uses it to seed `uploader-use-snowflake`,
`uploader-use-snowflake-shadow` and `messeging-use-snowflake`:

| Preset                 | uploader SF | shadow PG | messaging reads SF | Used by                                      |
|------------------------|-------------|-----------|--------------------|----------------------------------------------|
| `SnowflakeOnly`        | true        | false     | true               | nightly; daily too from IC-5808 phase 1      |
| `ShadowPostgreSqlRead` | true        | true      | false              | daily before IC-5808 (Reports read Postgres) |

So under `ShadowPostgreSqlRead` a daily run still writes the `_fakesnow` topics but Reports read Postgres, and
a broken fakesnow sink goes unnoticed. Under `SnowflakeOnly` daily Reports and Replay read fakesnow.

`isCaaSNightlyRun` also gates other nightly-only behaviour (e.g. `[RequiresCaaSNightlyRun]` tests). Note it
checks only the direct upstream job, while `snowFlakeEnvSetup` checks the whole chain.

## Why it was done this way (DEVOPS-4048)

- Not a production setting: the services would carry a test-only option and need a release for every change.
- Not "patch and restart at test start": adds 1-2 minutes per run, restarts count as failures, an aborted test
  leaves the namespace half-switched, and other projects use the namespace in parallel.
- Deploy-time `envsubst` keeps the services unaware and the namespace consistent from the first pod start.

## Forcing a mode by hand

`snowFlakeEnvSetup(true)` / `snowFlakeEnvSetup(false)` overrides the chain check. A manual run of the deploy
job alone gets fakesnow, because no `CaaS-EndToEnd-nightly` is upstream.
