# nuc-valkey — Best Practice Guide

**nuc-valkey** manages Valkey Operator CRD resources: ValkeyClusters and ValkeySentinels.

Valkey is an open-source Redis-compatible key-value store. The operator provides managed cluster and sentinel deployments on Kubernetes.

**Prerequisite:** Valkey Operator must be installed in the cluster.

## Enable

```yaml
nuc-valkey:
  enabled: true
```

## ValkeyClusters

### Minimal cluster (development)

```yaml
nuc-valkey:
  enabled: true
  valkeyclusters:
    cache:
      spec:
        image: valkey/valkey:8.1
        shards: 1
        replicas: 0
        workloadType: StatefulSet
```

### Production cluster (3 shards, 1 replica each)

```yaml
nuc-valkey:
  enabled: true
  valkeyclusters:
    cache:
      spec:
        image: valkey/valkey:8.1
        shards: 3
        replicas: 1
        workloadType: StatefulSet
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        storage:
          size: 10Gi
          storageClassName: standard
        config: |
          maxmemory 400mb
          maxmemory-policy allkeys-lru
          save ""
          appendonly no
        exporter:
          enabled: true
          image: oliver006/redis_exporter:v1.67.0
```

### With TLS

```yaml
nuc-valkey:
  enabled: true
  valkeyclusters:
    cache:
      spec:
        image: valkey/valkey:8.1
        shards: 3
        replicas: 1
        workloadType: StatefulSet
        tls:
          enabled: true
          secretName: valkey-tls       # cert-manager issued Secret
```

## ValkeySentinels (high-availability without clustering)

Sentinel mode provides HA with automatic failover for a single master + replicas topology:

```yaml
nuc-valkey:
  enabled: true
  valkeysentinels:
    session-store:
      spec:
        image: valkey/valkey:8.1
        replicas: 3          # 1 master + 2 replicas
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        storage:
          size: 5Gi
        config: |
          maxmemory 200mb
          maxmemory-policy volatile-lru
          appendonly yes
```

## Connecting to the cluster

For cluster mode, connect to the headless service:

```yaml
deployments:
  app:
    containers:
      app:
        env:
          REDIS_URL: redis://valkey-cache:6379
          # For cluster mode use a cluster-aware client
```

For sentinel mode, configure the client with sentinel addresses:

```yaml
deployments:
  app:
    containers:
      app:
        env:
          SENTINEL_HOSTS: "valkey-session-store-sentinel-0.valkey-session-store-sentinel:26379,valkey-session-store-sentinel-1.valkey-session-store-sentinel:26379,valkey-session-store-sentinel-2.valkey-session-store-sentinel:26379"
          SENTINEL_MASTER: mymaster
```

## Valkey configuration options

Key config parameters to set via `config: |`:

| Parameter | Purpose | Recommended |
|-----------|---------|-------------|
| `maxmemory` | Memory limit for data | 80% of container memory limit |
| `maxmemory-policy` | Eviction policy | `allkeys-lru` (cache), `volatile-lru` (session) |
| `save ""` | Disable RDB snapshots | For pure cache use cases |
| `appendonly yes` | Enable AOF persistence | For session stores requiring durability |
| `bind-source-addr ""` | Bind address | Leave empty for cluster |

## Best practices

- **Use cluster mode with 3+ shards** for large datasets — data is partitioned across shards, each with its own memory budget.
- **Use sentinel mode** for session stores and other single-master workloads that need HA without data partitioning.
- **Set `maxmemory` and `maxmemory-policy`** — without a memory limit Valkey will use all available container memory and be OOM-killed.
- **Use `allkeys-lru` for caches** (evict any key when full) and `volatile-lru` for stores that mix TTL-based and persistent keys.
- **Disable persistence (`save ""`, `appendonly no`)** for pure cache use cases — it reduces disk I/O and avoids blocking writes during BGSAVE.
- **Enable the exporter** (`exporter.enabled: true`) and configure a ServiceMonitor in nuc-kube-prometheus-stack or a VMServiceScrape in nuc-victoria-metrics.
- **Use TLS** in production environments where Valkey is accessed across namespaces or over untrusted networks.
