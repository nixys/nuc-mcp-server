# nuc-clickhouse — Best Practice Guide

**nuc-clickhouse** manages ClickHouse Operator CRD resources: ClickHouseInstallations, ClickHouseInstallationTemplates, ClickHouseKeeperInstallations, and ClickHouseOperatorConfigurations.

**Prerequisite:** ClickHouse Operator must be installed in the cluster.

## Enable

```yaml
nuc-clickhouse:
  enabled: true
```

## ClickHouseInstallations

### Minimal single-shard, single-replica (development)

```yaml
nuc-clickhouse:
  enabled: true
  clickhouseinstallations:
    analytics:
      spec:
        configuration:
          clusters:
            - name: default
              layout:
                shardsCount: 1
                replicasCount: 1
```

### Production: multi-shard with ClickHouse Keeper

```yaml
nuc-clickhouse:
  enabled: true
  clickhouseinstallations:
    analytics:
      spec:
        defaults:
          templates:
            podTemplate: ch-pod
            dataVolumeClaimTemplate: data
            logVolumeClaimTemplate: log
        configuration:
          zookeeper:
            nodes:
              - host: clickhouse-keeper
                port: 2181
          clusters:
            - name: default
              layout:
                shardsCount: 3
                replicasCount: 2
        templates:
          podTemplates:
            - name: ch-pod
              spec:
                containers:
                  - name: clickhouse
                    image: clickhouse/clickhouse-server:24.3
                    resources:
                      requests:
                        cpu: 1
                        memory: 4Gi
                      limits:
                        cpu: 4
                        memory: 16Gi
          volumeClaimTemplates:
            - name: data
              spec:
                accessModes:
                  - ReadWriteOnce
                storageClassName: fast-ssd
                resources:
                  requests:
                    storage: 500Gi
            - name: log
              spec:
                accessModes:
                  - ReadWriteOnce
                resources:
                  requests:
                    storage: 10Gi
```

## ClickHouseKeeperInstallations (replaces ZooKeeper)

ClickHouse Keeper is the recommended replacement for ZooKeeper as of ClickHouse 22.x:

```yaml
nuc-clickhouse:
  enabled: true
  clickhousekeeperinstallations:
    keeper:
      spec:
        replicas: 3
        templates:
          podTemplates:
            - name: keeper-pod
              spec:
                containers:
                  - name: clickhouse-keeper
                    image: clickhouse/clickhouse-keeper:24.3
                    resources:
                      requests:
                        cpu: 200m
                        memory: 256Mi
                      limits:
                        cpu: 500m
                        memory: 1Gi
          volumeClaimTemplates:
            - name: data
              spec:
                accessModes:
                  - ReadWriteOnce
                resources:
                  requests:
                    storage: 10Gi
```

## ClickHouseInstallationTemplates (reusable pod specs)

Define shared pod templates to avoid duplication across multiple installations:

```yaml
nuc-clickhouse:
  enabled: true
  clickhouseinstallationtemplates:
    default-layout:
      spec:
        templates:
          podTemplates:
            - name: ch-pod
              spec:
                containers:
                  - name: clickhouse
                    image: clickhouse/clickhouse-server:24.3
                    resources:
                      requests:
                        cpu: 2
                        memory: 8Gi
```

## Best practices

- **Use ClickHouse Keeper instead of ZooKeeper** for new deployments — it has lower memory overhead, simpler ops, and is the ClickHouse project's recommended coordination service.
- **Use 3 Keeper replicas** (odd number for quorum) and keep them on separate nodes with `affinity.podAntiAffinity`.
- **Separate data and log volumes** — log data grows quickly during high-throughput ingestion; having a separate volume prevents log growth from filling the data disk.
- **Size the `max_memory_usage`** server setting to 80% of the container memory limit — ClickHouse will otherwise consume all available memory and be OOM-killed.
- **Use `ReplicatedMergeTree` tables** (not `MergeTree`) when running replicated clusters — `MergeTree` data is not replicated across replicas.
- **Use `Distributed` tables** as a query layer over sharded `ReplicatedMergeTree` tables for transparent horizontal scaling.
- **Use ClickHouseInstallationTemplates** to define shared pod specs — this keeps individual installations concise and consistent.
