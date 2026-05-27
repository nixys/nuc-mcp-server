# nuc-victoria-metrics — Best Practice Guide

**nuc-victoria-metrics** manages VictoriaMetrics Operator CRD resources: VMAgents, VMSingles, VMClusters, VMAlerts, VMAlertmanagers, VMAlertmanagerConfigs, VMRules, VMServiceScrapes, VMPodScrapes, VMProbes, VMNodeScrapes, VMStaticScrapes, and VMUsers.

**Prerequisite:** VictoriaMetrics Operator must be installed in the cluster.

## Enable

```yaml
nuc-victoria-metrics:
  enabled: true
```

## VMSingle (single-node storage)

```yaml
nuc-victoria-metrics:
  enabled: true
  vmSingles:
    main:
      spec:
        retentionPeriod: "3"           # months
        replicaCount: 1
        storage:
          accessModes:
            - ReadWriteOnce
          resources:
            requests:
              storage: 50Gi
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2
            memory: 4Gi
```

## VMAgent (scraping)

Scrape Prometheus-format metrics and remote-write to storage:

```yaml
nuc-victoria-metrics:
  enabled: true
  vmAgents:
    default:
      spec:
        replicaCount: 1
        remoteWrite:
          - url: http://vmsingle-main-vmsingle:8428/api/v1/write
        serviceScrapeNamespaceSelector:
          matchLabels: {}        # scrape all namespaces
        podScrapeNamespaceSelector:
          matchLabels: {}
        resources:
          requests:
            cpu: 200m
            memory: 256Mi
```

## VMServiceScrapes

```yaml
nuc-victoria-metrics:
  enabled: true
  vmServiceScrapes:
    api:
      spec:
        selector:
          matchLabels:
            app: my-app
        endpoints:
          - port: metrics
            interval: 30s
            path: /metrics
```

## VMPodScrapes

```yaml
nuc-victoria-metrics:
  enabled: true
  vmPodScrapes:
    worker:
      spec:
        selector:
          matchLabels:
            app: worker
        podMetricsEndpoints:
          - port: metrics
            interval: 60s
```

## VMRules (alerting and recording)

```yaml
nuc-victoria-metrics:
  enabled: true
  vmRules:
    app-alerts:
      spec:
        groups:
          - name: app.alerts
            rules:
              - alert: AppDown
                expr: up{job="my-app"} == 0
                for: 2m
                labels:
                  severity: critical
                annotations:
                  summary: "App {{ $labels.instance }} is down"
```

## VMAlert

```yaml
nuc-victoria-metrics:
  enabled: true
  vmAlerts:
    main:
      spec:
        replicaCount: 1
        datasource:
          url: http://vmsingle-main-vmsingle:8428
        notifiers:
          - url: http://vmalertmanager-main-vmalertmanager:9093
        remoteRead:
          url: http://vmsingle-main-vmsingle:8428
        remoteWrite:
          url: http://vmsingle-main-vmsingle:8428/api/v1/write
        ruleNamespaceSelector:
          matchLabels: {}
        ruleSelector:
          matchLabels: {}
```

## VMAlertmanager

```yaml
nuc-victoria-metrics:
  enabled: true
  vmAlertmanagers:
    main:
      spec:
        replicaCount: 1
        configSecret: vmalertmanager-config   # Secret with alertmanager.yaml
```

## VMUser (multi-tenant access)

```yaml
nuc-victoria-metrics:
  enabled: true
  vmUsers:
    app-reader:
      spec:
        username: app-reader
        passwordRef:
          name: vmuser-passwords
          key: app-reader
        targetRefs:
          - crd:
              kind: VMSingle
              name: main
              namespace: monitoring
            paths:
              - /api/v1/query
              - /api/v1/query_range
```

## Best practices

- **Use VMAgent instead of Prometheus** for scraping when VictoriaMetrics is the storage backend — it has a smaller memory footprint and supports sharding.
- **Set `retentionPeriod` in months** on VMSingle — `"3"` means 3 months. Increase storage size proportionally.
- **Use `serviceScrapeNamespaceSelector: matchLabels: {}`** on VMAgent to scrape all namespaces automatically — no per-namespace config needed.
- **Use VMRules instead of PrometheusRules** when running VictoriaMetrics — both work, but VMRules support VictoriaMetrics-specific functions (MetricsQL).
- **Use VMUsers** for multi-tenant access control instead of exposing the VMSingle endpoint directly.
- **Avoid running VMCluster for small deployments** — VMSingle is sufficient for most workloads under 1M active time series and has simpler operational overhead.
