# nuc-knative — Best Practice Guide

**nuc-knative** manages Knative Serving CRD resources: Services, Revisions, Routes, and Configurations.

**Prerequisite:** Knative Serving must be installed in the cluster with a compatible network layer (Istio, Kourier, or Contour).

## Enable

```yaml
nuc-knative:
  enabled: true
```

## Knative Services

The primary resource — Knative manages Revisions, Routes, and Configurations automatically:

### Minimal service

```yaml
nuc-knative:
  enabled: true
  services:
    api:
      spec:
        template:
          spec:
            containers:
              - image: my-org/api:1.2.3
                ports:
                  - containerPort: 8080
```

### With autoscaling and concurrency

```yaml
nuc-knative:
  enabled: true
  services:
    api:
      spec:
        template:
          metadata:
            annotations:
              autoscaling.knative.dev/minScale: "1"
              autoscaling.knative.dev/maxScale: "50"
              autoscaling.knative.dev/target: "100"          # target concurrency per pod
              autoscaling.knative.dev/targetUtilization: "70"
          spec:
            containerConcurrency: 200          # max requests per pod
            timeoutSeconds: 300
            containers:
              - image: my-org/api:1.2.3
                ports:
                  - containerPort: 8080
                resources:
                  requests:
                    cpu: 100m
                    memory: 128Mi
                  limits:
                    cpu: 500m
                    memory: 512Mi
                env:
                  - name: ENV
                    value: production
                readinessProbe:
                  httpGet:
                    path: /readyz
                    port: 8080
                  initialDelaySeconds: 5
```

### Scale to zero (cold start)

```yaml
nuc-knative:
  enabled: true
  services:
    batch-api:
      spec:
        template:
          metadata:
            annotations:
              autoscaling.knative.dev/minScale: "0"   # allow scale to zero
              autoscaling.knative.dev/maxScale: "10"
              autoscaling.knative.dev/scaleToZeroGracePeriod: "30s"
          spec:
            containers:
              - image: my-org/batch-api:1.0.0
                ports:
                  - containerPort: 8080
```

### Traffic splitting between revisions

```yaml
nuc-knative:
  enabled: true
  services:
    api:
      spec:
        template:
          metadata:
            name: api-v2                        # named revision for traffic splitting
          spec:
            containers:
              - image: my-org/api:2.0.0
                ports:
                  - containerPort: 8080
        traffic:
          - revisionName: api-v1
            percent: 80
          - revisionName: api-v2
            percent: 20
```

## Revisions (explicit management)

Usually managed automatically by Knative — create explicit Revisions only when manual revision control is required:

```yaml
nuc-knative:
  enabled: true
  revisions:
    api-v1:
      spec:
        containerConcurrency: 100
        containers:
          - image: my-org/api:1.0.0
            ports:
              - containerPort: 8080
```

## Routes (custom traffic routing)

```yaml
nuc-knative:
  enabled: true
  routes:
    api:
      spec:
        traffic:
          - configurationName: api
            percent: 100
            tag: current
          - revisionName: api-v1
            percent: 0
            tag: previous
```

## Best practices

- **Set `minScale: 1`** for production services that cannot tolerate cold-start latency — scale-to-zero is useful only for bursty or rarely-used services.
- **Set `containerConcurrency`** based on your application's threading model — stateless Go/Rust apps can handle 200+, single-threaded Python apps should be lower (10–50).
- **Use `autoscaling.knative.dev/target`** (concurrency target) rather than CPU target — concurrency is a more natural metric for request-driven services.
- **Set resource limits** — Knative's autoscaler will create many small pods during scale-out; each pod must have enough resources to handle its share of concurrency.
- **Use named Revisions** when doing traffic splitting — this makes rollback explicit (set the old revision back to 100%) without re-deploying.
- **Combine with nuc-istio** — Knative integrates with Istio natively; use Istio as the network layer to get mTLS and observability for serverless workloads.
- **Use `readinessProbe`** to gate traffic routing — Knative will not route traffic to a pod until its readiness probe passes.
