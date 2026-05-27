# nxs-universal-chart — Best Practice Guides

Usage guides for **nxs-universal-chart** and all its dependency subcharts.
These docs are served by **nuc-chart-mcp** as `chart://catalog/docs/*.md` resources.

## Root chart

| Guide | Description |
|-------|-------------|
| [root-chart.md](root-chart.md) | Workloads, services, ingresses, jobs, config & storage |

## Subcharts

### Networking

| Guide | Subchart | Purpose |
|-------|----------|---------|
| [nuc-traefik.md](nuc-traefik.md) | nuc-traefik | Edge proxy — IngressRoutes, middleware, TLS |
| [nuc-istio.md](nuc-istio.md) | nuc-istio | Service mesh — Gateways, VirtualServices, mTLS |
| [nuc-native-gateway.md](nuc-native-gateway.md) | nuc-native-gateway | Kubernetes Gateway API — HTTPRoute, TLSRoute |
| [nuc-envoy-gateway.md](nuc-envoy-gateway.md) | nuc-envoy-gateway | Envoy Gateway — Backend, traffic policies |
| [nuc-certificates.md](nuc-certificates.md) | nuc-certificates | cert-manager — Issuers, Certificates, ACME |

### Observability

| Guide | Subchart | Purpose |
|-------|----------|---------|
| [nuc-kube-prometheus-stack.md](nuc-kube-prometheus-stack.md) | nuc-kube-prometheus-stack | Prometheus + Grafana — ServiceMonitors, alerting |
| [nuc-victoria-metrics.md](nuc-victoria-metrics.md) | nuc-victoria-metrics | VictoriaMetrics — VMAgent, VMSingle, VMAlert |
| [nuc-elk.md](nuc-elk.md) | nuc-elk | ELK stack (ECK) — Elasticsearch, Kibana, Beats |

### Secrets

| Guide | Subchart | Purpose |
|-------|----------|---------|
| [nuc-external-secrets.md](nuc-external-secrets.md) | nuc-external-secrets | External Secrets Operator — SecretStore, ExternalSecret |
| [nuc-vault-secret-operator.md](nuc-vault-secret-operator.md) | nuc-vault-secret-operator | Vault Secret Operator — VaultConnection, VaultAuth |

### Databases

| Guide | Subchart | Purpose |
|-------|----------|---------|
| [nuc-cloudnativepg.md](nuc-cloudnativepg.md) | nuc-cloudnativepg | CloudNativePG — PostgreSQL Cluster, Pooler |
| [nuc-mysql-percona-operator.md](nuc-mysql-percona-operator.md) | nuc-mysql-percona-operator | Percona XtraDB Cluster (MySQL HA) |
| [nuc-mongodb-percona-operator.md](nuc-mongodb-percona-operator.md) | nuc-mongodb-percona-operator | Percona Server MongoDB — ReplicaSet, Backups |
| [nuc-clickhouse.md](nuc-clickhouse.md) | nuc-clickhouse | ClickHouse Operator — Installations, Keeper |
| [nuc-valkey.md](nuc-valkey.md) | nuc-valkey | Valkey (Redis-compatible) — Cluster, Sentinel |
| [nuc-rabbitmq.md](nuc-rabbitmq.md) | nuc-rabbitmq | RabbitMQ — Policies, Exchanges, Queues |

### Autoscaling & Delivery

| Guide | Subchart | Purpose |
|-------|----------|---------|
| [nuc-keda.md](nuc-keda.md) | nuc-keda | KEDA — ScaledObject, TriggerAuthentication |
| [nuc-fluxcd.md](nuc-fluxcd.md) | nuc-fluxcd | Flux CD — GitRepository, Kustomization, HelmRelease |

### ML Platform

| Guide | Subchart | Purpose |
|-------|----------|---------|
| [nuc-knative.md](nuc-knative.md) | nuc-knative | Knative Serving — serverless workloads |
| [nuc-kserve.md](nuc-kserve.md) | nuc-kserve | KServe — InferenceService, ModelServer |

### Identity & Messaging

| Guide | Subchart | Purpose |
|-------|----------|---------|
| [nuc-keycloak-operator.md](nuc-keycloak-operator.md) | nuc-keycloak-operator | Keycloak Operator — Keycloak, Realm, Client |
| [nuc-strimzi-kafka-operator.md](nuc-strimzi-kafka-operator.md) | nuc-strimzi-kafka-operator | Strimzi Kafka Operator — Kafka, KafkaTopic, User |
