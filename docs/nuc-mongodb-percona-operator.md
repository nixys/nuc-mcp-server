# nuc-mongodb-percona-operator — Best Practice Guide

**nuc-mongodb-percona-operator** manages Percona Operator for MongoDB CRD resources: PerconaServerMongoDBs and PerconaServerMongoDBBackups.

**Prerequisite:** Percona Operator for MongoDB (PSMDB) must be installed in the cluster.

## Enable

```yaml
nuc-mongodb-percona-operator:
  enabled: true
```

## PerconaServerMongoDBs

### Minimal replica set (development)

```yaml
nuc-mongodb-percona-operator:
  enabled: true
  perconaServerMongoDBs:
    app-mongo:
      spec:
        crVersion: 1.17.0
        image: percona/percona-server-mongodb:7.0.12-7
        replsets:
          - name: rs0
            size: 1
            volumeSpec:
              persistentVolumeClaim:
                resources:
                  requests:
                    storage: 10Gi
        secrets:
          users: app-mongo-users
```

### Production HA replica set (3 nodes)

```yaml
nuc-mongodb-percona-operator:
  enabled: true
  perconaServerMongoDBs:
    app-mongo:
      spec:
        crVersion: 1.17.0
        image: percona/percona-server-mongodb:7.0.12-7
        replsets:
          - name: rs0
            size: 3
            resources:
              requests:
                cpu: 500m
                memory: 1Gi
              limits:
                cpu: 2
                memory: 4Gi
            volumeSpec:
              persistentVolumeClaim:
                storageClassName: fast-ssd
                resources:
                  requests:
                    storage: 100Gi
            configuration: |
              operationProfiling:
                mode: slowOp
                slowOpThresholdMs: 200
        secrets:
          users: app-mongo-users
        backup:
          enabled: true
          image: percona/percona-backup-mongodb:2.4.1
          storages:
            s3:
              type: s3
              s3:
                bucket: my-bucket
                region: us-east-1
                credentialsSecret: aws-credentials
          tasks:
            - name: daily
              enabled: true
              schedule: "0 3 * * *"
              keep: 7
              storageName: s3
              compressionType: gzip
```

### Sharded cluster

```yaml
nuc-mongodb-percona-operator:
  enabled: true
  perconaServerMongoDBs:
    app-mongo-sharded:
      spec:
        crVersion: 1.17.0
        image: percona/percona-server-mongodb:7.0.12-7
        sharding:
          enabled: true
          configsvrReplSet:
            size: 3
            volumeSpec:
              persistentVolumeClaim:
                resources:
                  requests:
                    storage: 10Gi
          mongos:
            size: 2
        replsets:
          - name: rs0
            size: 3
            volumeSpec:
              persistentVolumeClaim:
                resources:
                  requests:
                    storage: 100Gi
        secrets:
          users: app-mongo-users
```

## PerconaServerMongoDBBackups

Manual on-demand backup:

```yaml
nuc-mongodb-percona-operator:
  enabled: true
  perconaServerMongoDBBackups:
    manual:
      spec:
        psmdbCluster: app-mongo
        storageName: s3
        compressionType: gzip
```

## Secrets required by the operator

```yaml
# Secret: app-mongo-users
# Keys: MONGODB_BACKUP_USER, MONGODB_BACKUP_PASSWORD,
#        MONGODB_CLUSTER_ADMIN_USER, MONGODB_CLUSTER_ADMIN_PASSWORD,
#        MONGODB_CLUSTER_MONITOR_USER, MONGODB_CLUSTER_MONITOR_PASSWORD,
#        MONGODB_USER_ADMIN_USER, MONGODB_USER_ADMIN_PASSWORD
```

## Connecting to the cluster

The operator creates:
- `<name>-rs0` — headless service for the replica set
- `<name>-mongos` — service for the mongos router (sharded clusters)

```yaml
deployments:
  app:
    containers:
      app:
        env:
          MONGO_URI: mongodb://$(MONGO_USER):$(MONGO_PASSWORD)@app-mongo-rs0.default.svc.cluster.local/app?replicaSet=rs0
        envSecrets:
          - app-mongo-users
```

## Best practices

- **Use 3-node replica sets** in production — MongoDB requires a majority quorum; a 3-node set tolerates 1 failure.
- **Use sharding only when needed** — a replica set handles most workloads; sharding adds complexity (mongos routing, config servers).
- **Enable Percona Backup for MongoDB (PBM)** from day one — it supports both logical and physical backups and point-in-time recovery.
- **Set `crVersion`** to the exact installed CRD version — mismatches cause silent reconciliation failures.
- **Store all user credentials in a single Secret** referenced by `secrets.users` — manage it with nuc-vault-secret-operator.
- **Set resource limits** on replset pods — MongoDB uses all available memory for its WiredTiger cache by default; a container OOM will terminate the pod without graceful shutdown.
- **Enable profiling** (`operationProfiling.mode: slowOp`) and set a threshold to catch slow queries early in production.
