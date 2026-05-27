# nuc-rabbitmq — Best Practice Guide

**nuc-rabbitmq** manages RabbitMQ Messaging Topology Operator CRD resources: Policies, Exchanges, Queues, Bindings, Users, Vhosts, Permissions, SchemaReplications, and Federations.

**Prerequisite:** RabbitMQ Cluster Operator and Messaging Topology Operator must be installed in the cluster. A `RabbitmqCluster` resource must already exist (the subchart manages topology objects, not the cluster itself).

## Enable

```yaml
nuc-rabbitmq:
  enabled: true
```

## Policies

Define HA, TTL, and DLX policies:

```yaml
nuc-rabbitmq:
  enabled: true
  policies:
    ha-all:
      spec:
        name: ha-all
        pattern: .*
        applyTo: queues
        rabbitmqClusterReference:
          name: messaging
        definition:
          ha-mode: all
          ha-sync-mode: automatic
    ttl-30d:
      spec:
        name: ttl-30d
        pattern: ^archive\\.
        applyTo: queues
        rabbitmqClusterReference:
          name: messaging
        definition:
          message-ttl: 2592000000    # 30 days in milliseconds
    dlx:
      spec:
        name: dlx
        pattern: ^orders\\.
        applyTo: queues
        rabbitmqClusterReference:
          name: messaging
        definition:
          dead-letter-exchange: dlx
          dead-letter-routing-key: failed
```

## Exchanges

```yaml
nuc-rabbitmq:
  enabled: true
  exchanges:
    orders:
      spec:
        name: orders
        type: topic
        durable: true
        rabbitmqClusterReference:
          name: messaging
    events:
      spec:
        name: events
        type: fanout
        durable: true
        rabbitmqClusterReference:
          name: messaging
    dlx:
      spec:
        name: dlx
        type: direct
        durable: true
        rabbitmqClusterReference:
          name: messaging
```

## Queues

```yaml
nuc-rabbitmq:
  enabled: true
  queues:
    orders-processing:
      spec:
        name: orders.processing
        durable: true
        rabbitmqClusterReference:
          name: messaging
        arguments:
          x-dead-letter-exchange: dlx
          x-dead-letter-routing-key: orders.failed
          x-message-ttl: 86400000    # 1 day
    orders-failed:
      spec:
        name: orders.failed
        durable: true
        rabbitmqClusterReference:
          name: messaging
```

## Bindings

```yaml
nuc-rabbitmq:
  enabled: true
  bindings:
    orders-to-processing:
      spec:
        source: orders
        destination: orders.processing
        destinationType: queue
        routingKey: "order.#"
        rabbitmqClusterReference:
          name: messaging
```

## Users

```yaml
nuc-rabbitmq:
  enabled: true
  users:
    app:
      spec:
        rabbitmqClusterReference:
          name: messaging
        importCredentialsSecret:
          name: rabbitmq-app-credentials   # Secret with: username, password
```

## Vhosts

```yaml
nuc-rabbitmq:
  enabled: true
  vhosts:
    app:
      spec:
        name: app
        rabbitmqClusterReference:
          name: messaging
```

## Permissions

```yaml
nuc-rabbitmq:
  enabled: true
  permissions:
    app:
      spec:
        vhost: app
        user: app
        rabbitmqClusterReference:
          name: messaging
        permissions:
          configure: ".*"
          write: ".*"
          read: ".*"
```

## Best practices

- **Use topic exchanges** for event-driven architectures — routing keys provide flexible pub/sub routing without hardcoded queue names in producers.
- **Always configure a DLX** (Dead Letter Exchange) policy on processing queues — failed messages will be routed there instead of being silently dropped.
- **Set message TTL** on queues that should not accumulate stale messages — prevents unbounded memory growth when consumers are slow.
- **Apply the `ha-all` policy** in production to ensure queues are mirrored across all cluster nodes.
- **Use Permissions to scope user access** — producers should have write-only access to specific exchanges; consumers should have read-only access to specific queues.
- **Use separate Vhosts** for different applications or environments sharing the same cluster — Vhosts provide complete isolation of exchanges, queues, and users.
- **Store credentials in Kubernetes Secrets** referenced by `importCredentialsSecret` — manage them with nuc-vault-secret-operator.
