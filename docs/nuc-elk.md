# nuc-elk — Best Practice Guide

**nuc-elk** manages ECK (Elastic Cloud on Kubernetes) Operator CRD resources: Elasticsearches, Kibanas, Beats, Logstashes, APMServers, EnterpriseSearches, and Elastic Maps Servers.

**Prerequisite:** ECK Operator must be installed in the cluster.

## Enable

```yaml
nuc-elk:
  enabled: true
```

## Elasticsearch

```yaml
nuc-elk:
  enabled: true
  elasticsearches:
    logging:
      spec:
        version: 8.13.4
        nodeSets:
          - name: default
            count: 1
            config:
              node.store.allow_mmap: false   # required if vm.max_map_count cannot be set
            podTemplate:
              spec:
                containers:
                  - name: elasticsearch
                    resources:
                      requests:
                        memory: 2Gi
                        cpu: 500m
                      limits:
                        memory: 4Gi
                        cpu: 2
                    env:
                      - name: ES_JAVA_OPTS
                        value: "-Xms1g -Xmx1g"
            volumeClaimTemplates:
              - metadata:
                  name: elasticsearch-data
                spec:
                  accessModes:
                    - ReadWriteOnce
                  resources:
                    requests:
                      storage: 100Gi
        http:
          tls:
            selfSignedCertificate:
              disabled: true
```

### Multi-node production setup

```yaml
nuc-elk:
  enabled: true
  elasticsearches:
    logging:
      spec:
        version: 8.13.4
        nodeSets:
          - name: master
            count: 3
            config:
              node.roles: ["master"]
          - name: data
            count: 3
            config:
              node.roles: ["data", "ingest"]
            volumeClaimTemplates:
              - metadata:
                  name: elasticsearch-data
                spec:
                  accessModes:
                    - ReadWriteOnce
                  resources:
                    requests:
                      storage: 500Gi
                  storageClassName: fast-ssd
```

## Kibana

```yaml
nuc-elk:
  enabled: true
  kibanas:
    logging:
      spec:
        version: 8.13.4
        count: 1
        elasticsearchRef:
          name: logging
        http:
          tls:
            selfSignedCertificate:
              disabled: true
        config:
          xpack.fleet.enabled: false
```

## Beats (Filebeat, Metricbeat)

### Filebeat — ship logs from nodes

```yaml
nuc-elk:
  enabled: true
  beats:
    filebeat:
      spec:
        type: filebeat
        version: 8.13.4
        elasticsearchRef:
          name: logging
        daemonSet:
          podTemplate:
            spec:
              tolerations:
                - effect: NoSchedule
                  key: node-role.kubernetes.io/control-plane
              containers:
                - name: filebeat
                  resources:
                    requests:
                      cpu: 100m
                      memory: 200Mi
                    limits:
                      cpu: 500m
                      memory: 500Mi
        config:
          filebeat.inputs:
            - type: container
              paths:
                - /var/log/containers/*.log
          processors:
            - add_kubernetes_metadata:
                host: ${NODE_NAME}
                matchers:
                  - logs_path:
                      logs_path: "/var/log/containers/"
```

### Metricbeat — ship node/cluster metrics

```yaml
nuc-elk:
  enabled: true
  beats:
    metricbeat:
      spec:
        type: metricbeat
        version: 8.13.4
        elasticsearchRef:
          name: logging
        config:
          metricbeat.modules:
            - module: kubernetes
              metricsets:
                - container
                - node
                - pod
                - system
                - volume
              period: 10s
              host: ${NODE_NAME}
              hosts: ["https://${NODE_NAME}:10250"]
              bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
              ssl.verification_mode: "none"
```

## Logstash

```yaml
nuc-elk:
  enabled: true
  logstashes:
    pipeline:
      spec:
        version: 8.13.4
        count: 1
        elasticsearchRefs:
          - clusterID: logging
            name: logging
        pipelines:
          - pipeline.id: main
            config.string: |
              input { beats { port => 5044 } }
              filter {
                grok {
                  match => { "message" => "%{COMBINEDAPACHELOG}" }
                }
              }
              output {
                elasticsearch {
                  hosts => ["${LOGGING_ES_HOSTS}"]
                  user => "${LOGGING_ES_USER}"
                  password => "${LOGGING_ES_PASSWORD}"
                }
              }
```

## Best practices

- **Set `node.store.allow_mmap: false`** if you cannot set `vm.max_map_count=262144` on nodes — this avoids OOM issues at the cost of slightly lower performance.
- **Use Beats with `daemonSet`** for log and metric collection — DaemonSet ensures every node is covered, including nodes added later.
- **Set JVM heap to 50% of container memory limit** via `ES_JAVA_OPTS: "-Xms<n>g -Xmx<n>g"` — Elasticsearch needs the other half for OS file cache.
- **Use dedicated master nodes** in production (3 nodes with `node.roles: ["master"]`) — this prevents split-brain and protects cluster state.
- **Use `elasticsearchRef`** in Kibana and Beats to let ECK manage credentials automatically — avoid hardcoding passwords in config.
- **Disable TLS in development** with `selfSignedCertificate.disabled: true` to simplify local access; always enable TLS in production.
