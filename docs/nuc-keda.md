# nuc-keda — Best Practice Guide

**nuc-keda** manages KEDA (Kubernetes Event-Driven Autoscaling) CRD resources: ScaledObjects, ScaledJobs, TriggerAuthentications, and ClusterTriggerAuthentications.

**Prerequisite:** KEDA must be installed in the cluster.

## Enable

```yaml
nuc-keda:
  enabled: true
```

## ScaledObjects

Scale Deployments or StatefulSets based on external metrics.

### CPU / Memory (built-in)

```yaml
nuc-keda:
  enabled: true
  scaledObjects:
    api:
      spec:
        scaleTargetRef:
          apiVersion: apps/v1
          kind: Deployment
          name: api
        minReplicaCount: 2
        maxReplicaCount: 20
        cooldownPeriod: 60
        triggers:
          - type: cpu
            metricType: Utilization
            metadata:
              value: "70"
          - type: memory
            metricType: Utilization
            metadata:
              value: "80"
```

### RabbitMQ queue depth

```yaml
nuc-keda:
  enabled: true
  scaledObjects:
    worker:
      spec:
        scaleTargetRef:
          apiVersion: apps/v1
          kind: Deployment
          name: worker
        minReplicaCount: 1
        maxReplicaCount: 50
        pollingInterval: 15
        triggers:
          - type: rabbitmq
            authenticationRef:
              name: rabbitmq-auth
            metadata:
              protocol: amqp
              queueName: orders.processing
              mode: QueueLength
              value: "10"        # scale out when queue depth > 10 per replica
```

### Kafka consumer lag

```yaml
nuc-keda:
  enabled: true
  scaledObjects:
    kafka-consumer:
      spec:
        scaleTargetRef:
          apiVersion: apps/v1
          kind: Deployment
          name: kafka-consumer
        minReplicaCount: 1
        maxReplicaCount: 30
        triggers:
          - type: kafka
            authenticationRef:
              name: kafka-auth
            metadata:
              bootstrapServers: kafka-bootstrap:9092
              consumerGroup: my-app
              topic: events
              lagThreshold: "100"
              offsetResetPolicy: latest
```

### Prometheus / VictoriaMetrics query

```yaml
nuc-keda:
  enabled: true
  scaledObjects:
    api-prom:
      spec:
        scaleTargetRef:
          apiVersion: apps/v1
          kind: Deployment
          name: api
        minReplicaCount: 2
        maxReplicaCount: 20
        triggers:
          - type: prometheus
            metadata:
              serverAddress: http://vmsingle-main:8428
              metricName: http_requests_per_second
              query: |
                sum(rate(http_requests_total{job="api"}[2m]))
              threshold: "100"    # scale out when > 100 req/s per replica
```

### Scale to zero (cron + trigger)

```yaml
nuc-keda:
  enabled: true
  scaledObjects:
    api-schedule:
      spec:
        scaleTargetRef:
          apiVersion: apps/v1
          kind: Deployment
          name: api
        minReplicaCount: 0
        maxReplicaCount: 10
        triggers:
          - type: cron
            metadata:
              timezone: Europe/Moscow
              start: "0 9 * * 1-5"    # scale up at 9 AM on weekdays
              end: "0 19 * * 1-5"     # scale to 0 at 7 PM
              desiredReplicas: "3"
```

## ScaledJobs

Run batch jobs on demand based on external queue depth:

```yaml
nuc-keda:
  enabled: true
  scaledJobs:
    batch-processor:
      spec:
        jobTargetRef:
          template:
            spec:
              restartPolicy: Never
              containers:
                - name: processor
                  image: my-org/processor
                  imageTag: "1.0"
        minReplicaCount: 0
        maxReplicaCount: 20
        pollingInterval: 15
        successfulJobsHistoryLimit: 5
        failedJobsHistoryLimit: 5
        triggers:
          - type: rabbitmq
            authenticationRef:
              name: rabbitmq-auth
            metadata:
              protocol: amqp
              queueName: batch.tasks
              mode: QueueLength
              value: "1"
```

## TriggerAuthentications

```yaml
nuc-keda:
  enabled: true
  triggerAuthentications:
    rabbitmq-auth:
      spec:
        secretTargetRef:
          - parameter: host
            name: rabbitmq-app-credentials
            key: host
```

### Vault-based authentication

```yaml
nuc-keda:
  enabled: true
  triggerAuthentications:
    kafka-auth:
      spec:
        hashiCorpVault:
          address: https://vault.example.com:8200
          authentication: kubernetes
          mount: kubernetes
          role: keda
          credential:
            serviceAccount: keda-sa
          secrets:
            - parameter: username
              key: kafka_user
              path: apps/kafka/credentials
            - parameter: password
              key: kafka_password
              path: apps/kafka/credentials
```

## ClusterTriggerAuthentications (cluster-wide)

```yaml
nuc-keda:
  enabled: true
  clusterTriggerAuthentications:
    shared-rabbitmq:
      spec:
        secretTargetRef:
          - parameter: host
            name: shared-rabbitmq-credentials
            key: host
        podIdentity:
          provider: none
```

## Best practices

- **Set `minReplicaCount: 0`** for batch workloads — KEDA can scale to zero and back up, saving resources when there's no work.
- **Use `pollingInterval: 15`** for queue-based triggers — 5s causes excessive API calls; 30s+ adds too much latency for bursty workloads.
- **Use `cooldownPeriod: 60`** to prevent rapid scale-down after a burst — keeps replicas available for the next wave.
- **Use ScaledJobs** instead of ScaledObjects for batch tasks where each job processes one unit — prevents queue items from being processed multiple times by the same pod.
- **Use TriggerAuthentications** to decouple authentication from ScaledObjects — the same auth can be reused across multiple scalers.
- **Combine with RBAC** — KEDA needs read access to target resources; ensure its ServiceAccount has appropriate permissions.
- **Test scale-to-zero in staging** before enabling in production — some applications have long startup times that affect latency under sudden load.
