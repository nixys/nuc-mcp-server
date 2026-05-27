# nuc-cloudnativepg — Best Practice Guide

**nuc-cloudnativepg** manages CloudNativePG Operator CRD resources: Clusters, Poolers, Databases, Publications, Subscriptions, Backups, ScheduledBackups, ImageCatalogs, and ClusterImageCatalogs.

**Prerequisite:** CloudNativePG Operator must be installed in the cluster.

## Enable

```yaml
nuc-cloudnativepg:
  enabled: true
```

## Clusters

### Minimal single-node (development)

```yaml
nuc-cloudnativepg:
  enabled: true
  clusters:
    app-db:
      spec:
        instances: 1
        storage:
          size: 10Gi
```

### Production HA (3 instances)

```yaml
nuc-cloudnativepg:
  enabled: true
  clusters:
    app-db:
      spec:
        instances: 3
        postgresql:
          parameters:
            max_connections: "200"
            shared_buffers: "512MB"
            work_mem: "32MB"
            effective_cache_size: "1536MB"
        storage:
          size: 100Gi
          storageClass: fast-ssd
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2
            memory: 4Gi
        bootstrap:
          initdb:
            database: app
            owner: app
            secret:
              name: app-db-credentials   # Secret with username/password
        superuserSecret:
          name: app-db-superuser
        monitoring:
          enablePodMonitor: true
        backup:
          retentionPolicy: 7d
          barmanObjectStore:
            destinationPath: s3://my-bucket/postgres/app-db
            s3Credentials:
              accessKeyId:
                name: s3-credentials
                key: ACCESS_KEY_ID
              secretAccessKey:
                name: s3-credentials
                key: SECRET_ACCESS_KEY
```

### Read replicas

```yaml
nuc-cloudnativepg:
  enabled: true
  clusters:
    app-db-replica:
      spec:
        instances: 1
        storage:
          size: 100Gi
        externalClusters:
          - name: app-db-primary
            connectionParameters:
              host: app-db-rw.default.svc.cluster.local
              user: postgres
              dbname: app
              sslmode: require
            password:
              name: app-db-superuser
              key: password
        replica:
          enabled: true
          source: app-db-primary
```

## Poolers (PgBouncer)

```yaml
nuc-cloudnativepg:
  enabled: true
  poolers:
    app-db:
      spec:
        cluster:
          name: app-db
        instances: 2
        type: rw                   # rw (read-write) or ro (read-only)
        pgbouncer:
          poolMode: transaction    # transaction, session, or statement
          parameters:
            max_client_conn: "200"
            default_pool_size: "20"
            reserve_pool_size: "5"
```

## Databases

```yaml
nuc-cloudnativepg:
  enabled: true
  databases:
    app:
      spec:
        name: app
        owner: app
        cluster:
          name: app-db
```

## ScheduledBackups

```yaml
nuc-cloudnativepg:
  enabled: true
  scheduledBackups:
    daily:
      spec:
        schedule: "0 3 * * *"     # 3 AM daily
        cluster:
          name: app-db
        backupOwnerReference: self
        immediate: true            # take a backup immediately on creation
```

## Best practices

- **Use 3 instances in production** — CloudNativePG promotes a replica automatically if the primary fails, with no data loss (synchronous replication available).
- **Use PgBouncer Poolers in `transaction` mode** for stateless applications — it multiplexes many client connections over a small number of server connections.
- **Set `monitoring.enablePodMonitor: true`** to automatically expose PostgreSQL metrics for Prometheus/VictoriaMetrics scraping.
- **Configure S3-compatible backup** (`barmanObjectStore`) from day one — it enables PITR (Point-in-Time Recovery) and cross-region DR.
- **Use `externalClusters` + `replica.enabled: true`** for cross-cluster read replicas or disaster recovery replicas in a secondary cluster.
- **Store credentials in Kubernetes Secrets** referenced via `bootstrap.initdb.secret` and `superuserSecret` — never hardcode passwords in values.
- **Set PostgreSQL parameters** (`shared_buffers`, `work_mem`, `effective_cache_size`) to 25%/4MB/75% of the container's memory limit respectively.
