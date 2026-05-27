# nuc-strimzi-kafka-operator — Best Practice Guide

**nuc-strimzi-kafka-operator** manages Strimzi Kafka Operator CRD resources: Kafkas, KafkaTopics, KafkaUsers, KafkaConnects, KafkaMirrorMaker2s, KafkaBridges, and KafkaRebalances.

**Prerequisite:** Strimzi Kafka Operator must be installed in the cluster.

## Enable

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
```

## Kafkas

### Minimal cluster with KRaft (no ZooKeeper)

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkas:
    events:
      spec:
        kafka:
          version: 3.7.0
          metadataVersion: 3.7-IV4
          replicas: 1
          listeners:
            - name: plain
              port: 9092
              type: internal
              tls: false
          config:
            offsets.topic.replication.factor: 1
            transaction.state.log.replication.factor: 1
            transaction.state.log.min.isr: 1
            default.replication.factor: 1
            min.insync.replicas: 1
          storage:
            type: ephemeral
        entityOperator:
          topicOperator: {}
          userOperator: {}
```

### Production HA cluster (3 brokers + KRaft)

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkas:
    events:
      spec:
        kafka:
          version: 3.7.0
          metadataVersion: 3.7-IV4
          replicas: 3
          listeners:
            - name: plain
              port: 9092
              type: internal
              tls: false
            - name: tls
              port: 9093
              type: internal
              tls: true
          config:
            offsets.topic.replication.factor: 3
            transaction.state.log.replication.factor: 3
            transaction.state.log.min.isr: 2
            default.replication.factor: 3
            min.insync.replicas: 2
            log.retention.hours: 168          # 7 days
            log.segment.bytes: 1073741824     # 1GB
            num.partitions: 6
          storage:
            type: persistent-claim
            size: 100Gi
            class: fast-ssd
            deleteClaim: false
          resources:
            requests:
              cpu: 500m
              memory: 2Gi
            limits:
              cpu: 2
              memory: 4Gi
          jvmOptions:
            -Xms: "1536m"
            -Xmx: "1536m"
        entityOperator:
          topicOperator: {}
          userOperator: {}
```

### External access (LoadBalancer)

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkas:
    events:
      spec:
        kafka:
          replicas: 3
          listeners:
            - name: external
              port: 9094
              type: loadbalancer
              tls: true
              authentication:
                type: tls
```

## KafkaTopics

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkaTopics:
    orders:
      spec:
        partitions: 6
        replicas: 3
        config:
          retention.ms: 604800000       # 7 days
          segment.bytes: 1073741824     # 1GB
          cleanup.policy: delete
          min.insync.replicas: 2
    orders-dlq:
      spec:
        partitions: 1
        replicas: 3
        config:
          retention.ms: 2592000000      # 30 days
          cleanup.policy: delete
    events-compact:
      spec:
        partitions: 12
        replicas: 3
        config:
          cleanup.policy: compact
          min.cleanable.dirty.ratio: "0.5"
          segment.ms: 3600000           # 1 hour
```

## KafkaUsers

### TLS client (certificate authentication)

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkaUsers:
    producer:
      spec:
        authentication:
          type: tls
        authorization:
          type: simple
          acls:
            - resource:
                type: topic
                name: orders
              operations:
                - Write
                - Describe
            - resource:
                type: transactionalId
                name: my-app-producer
              operations:
                - Write
```

### SCRAM-SHA-512 (username/password)

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkaUsers:
    consumer:
      spec:
        authentication:
          type: scram-sha-512
        authorization:
          type: simple
          acls:
            - resource:
                type: topic
                name: orders
              operations:
                - Read
                - Describe
            - resource:
                type: group
                name: my-app-consumer-group
              operations:
                - Read
```

## KafkaConnects

Managed Kafka Connect cluster:

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkaConnects:
    main:
      spec:
        version: 3.7.0
        replicas: 2
        bootstrapServers: events-kafka-bootstrap:9092
        config:
          group.id: connect-cluster
          offset.storage.topic: connect-cluster-offsets
          config.storage.topic: connect-cluster-configs
          status.storage.topic: connect-cluster-status
          config.storage.replication.factor: 3
          offset.storage.replication.factor: 3
          status.storage.replication.factor: 3
        build:
          output:
            type: docker
            image: registry.example.com/my-org/kafka-connect:latest
            pushSecret: registry-credentials
          plugins:
            - name: debezium-postgres
              artifacts:
                - type: maven
                  group: io.debezium
                  artifact: debezium-connector-postgres
                  version: 2.6.2.Final
```

## KafkaMirrorMaker2s (cross-cluster replication)

```yaml
nuc-strimzi-kafka-operator:
  enabled: true
  kafkaMirrorMaker2s:
    dc-replication:
      spec:
        version: 3.7.0
        replicas: 1
        connectCluster: target
        clusters:
          - alias: source
            bootstrapServers: source-kafka-bootstrap:9092
          - alias: target
            bootstrapServers: target-kafka-bootstrap:9092
        mirrors:
          - sourceCluster: source
            targetCluster: target
            sourceConnector:
              config:
                replication.factor: 3
                offset-syncs.topic.replication.factor: 3
                sync.topic.acls.enabled: false
            topicsPattern: "orders.*"
            groupsPattern: ".*"
```

## Best practices

- **Use KRaft mode** (no ZooKeeper) for new clusters — set `metadataVersion` matching the Kafka version; KRaft is stable from Kafka 3.3+.
- **Set `min.insync.replicas: 2`** and `replication.factor: 3` for production topics — ensures data durability even if one broker is down.
- **Partition count = parallelism** — set partitions to at least the number of consumer group members; increasing partitions later is possible but requires careful planning.
- **Use KafkaUsers with TLS** for producer/consumer authentication — it integrates with Strimzi's certificate management without external CA setup.
- **Use ACLs via KafkaUser** to restrict producer/consumer access to specific topics — avoid using the `kafka-super-user` for application workloads.
- **Set JVM heap to 75% of memory limit** (`-Xms`/`-Xmx`) — Kafka uses the remaining memory for OS page cache, which is critical for performance.
- **Enable entityOperator** (topicOperator + userOperator) on the Kafka resource — it enables automatic reconciliation of KafkaTopic and KafkaUser resources.
