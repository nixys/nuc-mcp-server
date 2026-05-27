# nuc-mysql-percona-operator — Best Practice Guide

**nuc-mysql-percona-operator** manages Percona Operator for MySQL CRD resources: PerconaXtraDBClusters and PerconaXtraDBClusterBackups.

**Prerequisite:** Percona Operator for MySQL (PXC) must be installed in the cluster.

## Enable

```yaml
nuc-mysql-percona-operator:
  enabled: true
```

## PerconaXtraDBClusters

### Minimal single-node (development)

```yaml
nuc-mysql-percona-operator:
  enabled: true
  perconaXtraDBClusters:
    app-mysql:
      spec:
        crVersion: 1.16.0
        secretsName: app-mysql-secrets     # Secret: root, xtrabackup, monitor, clustercheck, proxyadmin, operator
        pxc:
          size: 1
          image: percona/percona-xtradb-cluster:8.0.36
          volumeSpec:
            persistentVolumeClaim:
              resources:
                requests:
                  storage: 10Gi
        haproxy:
          enabled: true
          size: 1
          image: percona/percona-xtradb-cluster-operator:1.16.0-haproxy
```

### Production HA (3 nodes + HAProxy)

```yaml
nuc-mysql-percona-operator:
  enabled: true
  perconaXtraDBClusters:
    app-mysql:
      spec:
        crVersion: 1.16.0
        secretsName: app-mysql-secrets
        pxc:
          size: 3
          image: percona/percona-xtradb-cluster:8.0.36
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
            [mysqld]
            max_connections=500
            innodb_buffer_pool_size=2G
            innodb_log_file_size=256M
        haproxy:
          enabled: true
          size: 2
          image: percona/percona-xtradb-cluster-operator:1.16.0-haproxy
        backup:
          image: percona/percona-xtradb-cluster-operator:1.16.0-pxc8.0-backup
          storages:
            s3:
              type: s3
              s3:
                bucket: my-bucket
                region: us-east-1
                credentialsSecret: aws-credentials
          schedule:
            - name: daily
              schedule: "0 2 * * *"
              keep: 7
              storageName: s3
```

## PerconaXtraDBClusterBackups

Manual on-demand backup:

```yaml
nuc-mysql-percona-operator:
  enabled: true
  perconaXtraDBClusterBackups:
    manual-backup:
      spec:
        pxcCluster: app-mysql
        storageName: s3
```

## Secrets required by the operator

The `secretsName` Secret must contain these keys:

```yaml
# Secret: app-mysql-secrets
apiVersion: v1
kind: Secret
metadata:
  name: app-mysql-secrets
stringData:
  root: <root-password>
  xtrabackup: <xtrabackup-password>
  monitor: <monitor-password>
  clustercheck: <clustercheck-password>
  proxyadmin: <proxyadmin-password>
  operator: <operator-password>
  replication: <replication-password>    # required for async replication
```

Manage this Secret with nuc-vault-secret-operator or nuc-external-secrets.

## Connecting to the cluster

HAProxy exposes two services:
- `<cluster>-haproxy` — port 3306 (read-write, routes to primary)
- `<cluster>-haproxy-replicas` — port 3306 (read-only, load-balances across replicas)

```yaml
# In the root chart deployment:
deployments:
  app:
    containers:
      app:
        envSecrets:
          - app-mysql-secrets
        env:
          DB_HOST: app-mysql-haproxy
          DB_PORT: "3306"
```

## Best practices

- **Use 3 PXC nodes** for production — Galera requires an odd number to achieve quorum.
- **Enable HAProxy** (not ProxySQL) for stateless applications — HAProxy correctly routes writes to the primary and reads to replicas.
- **Set `innodb_buffer_pool_size`** to 50–75% of the container's memory limit — it is the most important InnoDB performance parameter.
- **Configure S3-compatible backup** from day one via the `backup.schedule` field — Percona XtraBackup supports incremental backups.
- **Store all operator-required passwords in a single Secret** referenced by `secretsName` — use nuc-vault-secret-operator to generate and rotate them automatically.
- **Set `crVersion`** to the exact version of the installed CRD — version mismatches cause reconciliation errors.
