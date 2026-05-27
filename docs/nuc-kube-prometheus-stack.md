# nuc-kube-prometheus-stack — Best Practice Guide

**nuc-kube-prometheus-stack** manages kube-prometheus-stack CRD resources: ServiceMonitors, PodMonitors, PrometheusRules, AlertmanagerConfigs, and Probes.

**Prerequisite:** kube-prometheus-stack must be installed in the cluster (Prometheus Operator + Alertmanager + Grafana).

## Enable

```yaml
nuc-kube-prometheus-stack:
  enabled: true
```

## ServiceMonitors

Scrape metrics from Kubernetes Services:

```yaml
nuc-kube-prometheus-stack:
  enabled: true
  serviceMonitors:
    api:
      spec:
        selector:
          matchLabels:
            app: my-app
        namespaceSelector:
          matchNames:
            - default
        endpoints:
          - port: metrics
            interval: 30s
            path: /metrics
            scheme: http
```

### With TLS and authentication

```yaml
nuc-kube-prometheus-stack:
  enabled: true
  serviceMonitors:
    secure-api:
      spec:
        selector:
          matchLabels:
            app: my-app
        endpoints:
          - port: metrics
            interval: 15s
            scheme: https
            tlsConfig:
              insecureSkipVerify: false
              caFile: /etc/prometheus/certs/ca.crt
            bearerTokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
```

## PodMonitors

Scrape metrics directly from Pods (when Service-level scraping is not available):

```yaml
nuc-kube-prometheus-stack:
  enabled: true
  podMonitors:
    worker:
      spec:
        selector:
          matchLabels:
            app: worker
        podMetricsEndpoints:
          - port: metrics
            interval: 60s
            path: /metrics
```

## PrometheusRules

Define alerting and recording rules:

```yaml
nuc-kube-prometheus-stack:
  enabled: true
  prometheusRules:
    app-alerts:
      spec:
        groups:
          - name: app.rules
            rules:
              - alert: AppHighErrorRate
                expr: |
                  rate(http_requests_total{status=~"5.."}[5m])
                  / rate(http_requests_total[5m]) > 0.05
                for: 5m
                labels:
                  severity: warning
                annotations:
                  summary: "High error rate on {{ $labels.job }}"
                  description: "Error rate is {{ $value | humanizePercentage }}"

          - name: app.recording
            rules:
              - record: job:http_requests:rate5m
                expr: rate(http_requests_total[5m])
```

## AlertmanagerConfigs

Configure alert routing and receivers:

```yaml
nuc-kube-prometheus-stack:
  enabled: true
  alertmanagerConfigs:
    app-alerts:
      spec:
        route:
          groupBy:
            - alertname
            - namespace
          groupWait: 30s
          groupInterval: 5m
          repeatInterval: 4h
          receiver: slack-ops
          routes:
            - match:
                severity: critical
              receiver: pagerduty-oncall
        receivers:
          - name: slack-ops
            slackConfigs:
              - channel: "#ops-alerts"
                apiURL:
                  name: alertmanager-slack-secret
                  key: webhook-url
                title: "{{ .GroupLabels.alertname }}"
                text: "{{ range .Alerts }}{{ .Annotations.description }}\n{{ end }}"
          - name: pagerduty-oncall
            pagerdutyConfigs:
              - routingKey:
                  name: alertmanager-pagerduty-secret
                  key: routing-key
```

## Probes

Blackbox monitoring (HTTP, TCP probes):

```yaml
nuc-kube-prometheus-stack:
  enabled: true
  probes:
    api-health:
      spec:
        prober:
          url: blackbox-exporter:9115
          scheme: http
          path: /probe
        module: http_2xx
        targets:
          staticConfig:
            static:
              - https://api.example.com/healthz
              - https://api.example.com/readyz
        interval: 60s
        scrapeTimeout: 10s
```

## Best practices

- **Label workloads consistently** — ServiceMonitors and PodMonitors match by labels; consistent `app`, `component`, and `version` labels across all pods simplify selector configuration.
- **Use `namespaceSelector`** to restrict scraping to relevant namespaces; avoid `any: true` in production as it scrapes all namespaces including system workloads.
- **Set `interval` per sensitivity** — 15s for SLO-critical services, 30–60s for background workers to reduce Prometheus storage.
- **Use recording rules** for expensive queries (high-cardinality aggregations) — pre-compute them with `record:` and reference the metric name in dashboards and alerting rules.
- **Combine with nuc-victoria-metrics** — if VictoriaMetrics is used instead of Prometheus, it also supports PrometheusRule and ServiceMonitor CRDs, so the same subchart config works with both backends.
- **Use AlertmanagerConfig `inhibitRules`** to suppress lower-severity alerts when a parent alert fires (e.g., suppress pod-level warnings when the deployment-level critical alert is active).
