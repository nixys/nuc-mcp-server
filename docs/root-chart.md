# nxs-universal-chart — Root Chart Guide

**nxs-universal-chart** is a generic Helm application chart that renders Kubernetes workloads,
services, config, storage, and job resources from a unified `values.yaml`.
It delegates infrastructure concerns (ingress, service mesh, databases, secrets) to enabled subcharts.

## Quick start

```yaml
nameOverride: my-app        # base name for all resource names and labels
releasePrefix: ""           # set "-" to drop the Helm release-name prefix

deployments:
  api:
    containers:
      api:
        image: my-org/api
        imageTag: "1.2.3"
        ports:
          - name: http
            containerPort: 8080

services:
  api:
    enabled: true
    selector:
      app: my-app
    ports:
      - name: http
        port: 80
        targetPort: http
```

## Top-level keys

| Key | Purpose |
|-----|---------|
| `nameOverride` | Override the application name used in all resource labels and names |
| `releasePrefix` | Prefix prepended to rendered resource names. Use `"-"` to drop the release-name prefix |
| `kubeVersion` | Override the Kubernetes version for capability checks |
| `workloadMode` | Restrict rendered controllers: `auto`, `deployment`, `daemonset`, `statefulset`, `pod`, `batch`, `job`, `cronjob`, `hook`, `none` |
| `gitops` | GitOps metadata: `commonLabels`, `commonAnnotations`, Argo CD and Flux annotations |
| `generic` | Shared defaults applied to all workloads (resources, tolerations, nodeSelector, securityContext, volumes, imagePullSecrets) |

## Workloads

### Deployments

```yaml
deployments:
  api:
    replicas: 2
    labels:
      app: my-app
    containers:
      api:
        image: nginx
        imageTag: "1.27.5"
        ports:
          - name: http
            containerPort: 8080
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
        envs:
          ENV_VAR: value
        envSecrets:
          - my-secret         # mounts env vars from a Kubernetes Secret
        envConfigMaps:
          - my-config         # mounts env vars from a ConfigMap
        livenessProbe:
          httpGet:
            path: /healthz
            port: http
          initialDelaySeconds: 5
        readinessProbe:
          httpGet:
            path: /readyz
            port: http
```

### DaemonSets

```yaml
daemonSets:
  agent:
    containers:
      agent:
        image: my-org/agent
        imageTag: latest
```

### StatefulSets

```yaml
statefulSets:
  db:
    replicas: 1
    containers:
      db:
        image: postgres
        imageTag: "16"
        ports:
          - name: pg
            containerPort: 5432
    volumeClaimTemplates:
      data:
        spec:
          accessModes: [ReadWriteOnce]
          resources:
            requests:
              storage: 10Gi
```

### Pods (standalone)

```yaml
pods:
  debug:
    containers:
      debug:
        image: busybox
        imageTag: "1.36.1"
        command: ["/bin/sh", "-c", "sleep 3600"]
```

## Jobs and hooks

### One-time Jobs

```yaml
jobs:
  migration:
    containers:
      - name: migration
        image: my-org/migrator
        imageTag: "1.0"
        command: ["python", "manage.py", "migrate"]
    restartPolicy: Never
    backoffLimit: 3
```

### CronJobs

```yaml
cronJobs:
  cleanup:
    schedule: "0 2 * * *"
    containers:
      - name: cleanup
        image: my-org/cleanup
        imageTag: "1.0"
```

### Hooks (Helm lifecycle)

```yaml
hooks:
  pre-upgrade:
    annotations:
      helm.sh/hook: pre-upgrade
      helm.sh/hook-weight: "-1"
      helm.sh/hook-delete-policy: before-hook-creation
    containers:
      - name: migrate
        image: my-org/migrator
        imageTag: "1.0"
        command: ["python", "manage.py", "migrate"]
    restartPolicy: Never
```

## Services and networking

### Services

```yaml
services:
  api:
    enabled: true
    labels:
      app: my-app
    selector:
      app: my-app
    ports:
      - name: http
        port: 80
        targetPort: http
    type: ClusterIP       # ClusterIP (default), NodePort, LoadBalancer
```

### Ingresses

```yaml
ingresses:
  api:
    enabled: true
    ingressClassName: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt
    tls:
      - hosts:
          - api.example.com
        secretName: api-tls
    rules:
      - host: api.example.com
        http:
          paths:
            - path: /
              pathType: Prefix
              backend:
                service:
                  name: api
                  port:
                    name: http
```

### NetworkPolicies

```yaml
networkPolicies:
  api:
    podSelector:
      matchLabels:
        app: my-app
    policyTypes:
      - Ingress
    ingress:
      - from:
          - podSelector:
              matchLabels:
                app: frontend
```

## Config and secrets

### ConfigMaps

```yaml
configMaps:
  app-config:
    data:
      config.yaml: |
        log_level: info
        feature_flags:
          new_ui: true
```

### Secrets

```yaml
secrets:
  app-secret:
    data:
      DATABASE_URL: <base64-encoded>
      API_KEY: <base64-encoded>
    stringData:            # alternative — plain text, Helm encodes at render time
      TOKEN: my-token
```

### SealedSecrets

```yaml
sealedSecrets:
  app-secret:
    encryptedData:
      TOKEN: <sealed-value>
```

## Storage

### PersistentVolumes

```yaml
pvs:
  data:
    spec:
      capacity:
        storage: 10Gi
      accessModes:
        - ReadWriteOnce
      storageClassName: standard
      persistentVolumeReclaimPolicy: Retain
      hostPath:
        path: /data/my-app
```

### PersistentVolumeClaims

```yaml
pvcs:
  data:
    spec:
      accessModes:
        - ReadWriteOnce
      storageClassName: standard
      resources:
        requests:
          storage: 10Gi
```

## Autoscaling

### HPAs

```yaml
hpas:
  api:
    spec:
      scaleTargetRef:
        apiVersion: apps/v1
        kind: Deployment
        name: my-app-api
      minReplicas: 2
      maxReplicas: 10
      metrics:
        - type: Resource
          resource:
            name: cpu
            target:
              type: Utilization
              averageUtilization: 70
```

### PodDisruptionBudgets

```yaml
pdbs:
  api:
    spec:
      minAvailable: 1
      selector:
        matchLabels:
          app: my-app
```

## Shared defaults (`generic`)

Use `generic` to apply defaults to all workloads without repeating them:

```yaml
generic:
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 256Mi
  tolerations:
    - key: dedicated
      operator: Equal
      value: app
      effect: NoSchedule
  nodeSelector:
    kubernetes.io/os: linux
  podSecurityContext:
    runAsNonRoot: true
    runAsUser: 1000
  imagePullSecrets:
    - name: registry-credentials
  autoRolloutChecksums: true   # add checksum annotations for ConfigMaps/Secrets
```

## GitOps annotations

### Argo CD

```yaml
gitops:
  commonLabels:
    team: platform
  argo:
    enabled: true
    syncWave: "5"
    syncOptions:
      - ServerSideApply=true
```

### Flux CD

```yaml
gitops:
  flux:
    enabled: true
    labels:
      kustomize.toolkit.fluxcd.io/name: my-app
```

## Environment variables

```yaml
envs:                    # top-level shared env map (all pods)
  LOG_LEVEL: info
  APP_ENV: production

defaultImage:            # default image for all containers (optional)
  registry: registry.example.com
  pullPolicy: IfNotPresent

imagePullSecrets:        # top-level imagePullSecrets (all workloads)
  - registry-credentials
```

## Best practices

- **Use `nameOverride`** on every release — makes resource names predictable and independent of the Helm release name.
- **Use `releasePrefix: "-"`** in GitOps environments where you render multiple releases in one namespace.
- **Use `generic.resources`** to set baseline CPU/memory instead of repeating per container.
- **Use `generic.autoRolloutChecksums: true`** (default) so Deployments restart automatically when a ConfigMap or Secret changes.
- **Use `hooks` with `helm.sh/hook-weight`** for ordered pre-upgrade migrations before any Deployment rollout.
- **Avoid top-level `envs` for secrets** — prefer `envSecrets` referencing a Kubernetes Secret managed by nuc-vault-secret-operator or nuc-external-secrets.
- **Enable subcharts selectively** — each subchart requires cluster-level CRDs; only enable what is already installed in the cluster.
- **Use `workloadMode`** to restrict the renderer to only generate expected resource types (e.g., `job` for migration charts).
