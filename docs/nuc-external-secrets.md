# nuc-external-secrets — Best Practice Guide

**nuc-external-secrets** manages External Secrets Operator CRD resources: SecretStores, ClusterSecretStores, ExternalSecrets, ClusterExternalSecrets, PushSecrets, and generator resources (Password, ECRAuthorizationToken, GCRAccessToken, ACRAccessToken, GithubAccessToken, VaultDynamicSecret, ClusterGenerator).

**Prerequisite:** External Secrets Operator (ESO) must be installed in the cluster.

## Enable

```yaml
nuc-external-secrets:
  enabled: true
```

## SecretStores

### AWS Secrets Manager

```yaml
nuc-external-secrets:
  enabled: true
  secretStores:
    aws:
      spec:
        provider:
          aws:
            service: SecretsManager
            region: us-east-1
            auth:
              jwt:
                serviceAccountRef:
                  name: external-secrets-sa
```

### HashiCorp Vault

```yaml
nuc-external-secrets:
  enabled: true
  secretStores:
    vault:
      spec:
        provider:
          vault:
            server: https://vault.example.com:8200
            path: secret
            version: v2
            auth:
              kubernetes:
                mountPath: kubernetes
                role: my-app
                serviceAccountRef:
                  name: external-secrets-sa
```

### GCP Secret Manager

```yaml
nuc-external-secrets:
  enabled: true
  secretStores:
    gcp:
      spec:
        provider:
          gcpsm:
            projectID: my-project
            auth:
              workloadIdentity:
                clusterLocation: us-central1
                clusterName: my-cluster
                serviceAccountRef:
                  name: external-secrets-sa
```

### Fake provider (development/testing)

```yaml
nuc-external-secrets:
  enabled: true
  secretStores:
    fake:
      spec:
        provider:
          fake:
            data:
              - key: /app/config
                value: '{"username":"demo","password":"demo-password"}'
                version: v1
```

## ClusterSecretStores (cluster-wide)

```yaml
nuc-external-secrets:
  enabled: true
  clusterSecretStores:
    vault:
      spec:
        provider:
          vault:
            server: https://vault.example.com:8200
            path: secret
            version: v2
            auth:
              kubernetes:
                mountPath: kubernetes
                role: cluster-reader
```

## ExternalSecrets

Sync external secrets into Kubernetes Secrets:

```yaml
nuc-external-secrets:
  enabled: true
  externalSecrets:
    app-config:
      spec:
        refreshInterval: 1h
        secretStoreRef:
          kind: SecretStore
          name: vault
        target:
          name: app-config         # name of the Kubernetes Secret to create
          creationPolicy: Owner
        data:
          - secretKey: DATABASE_URL
            remoteRef:
              key: apps/my-app/db
              property: url
          - secretKey: API_KEY
            remoteRef:
              key: apps/my-app/api
              property: key
```

### Sync all keys from a path

```yaml
nuc-external-secrets:
  enabled: true
  externalSecrets:
    app-all:
      spec:
        refreshInterval: 30m
        secretStoreRef:
          kind: ClusterSecretStore
          name: vault
        target:
          name: app-all
          creationPolicy: Owner
        dataFrom:
          - extract:
              key: apps/my-app/config
```

## ClusterExternalSecrets (sync to multiple namespaces)

```yaml
nuc-external-secrets:
  enabled: true
  clusterExternalSecrets:
    shared-config:
      spec:
        namespaceSelectors:
          - matchLabels:
              shared-secrets: "true"
        refreshTime: 1h
        externalSecretSpec:
          refreshInterval: 1h
          secretStoreRef:
            kind: ClusterSecretStore
            name: vault
          target:
            name: shared-config
            creationPolicy: Owner
          dataFrom:
            - extract:
                key: shared/config
```

## PushSecrets (push to external store)

```yaml
nuc-external-secrets:
  enabled: true
  pushSecrets:
    app-secret:
      spec:
        refreshInterval: 1h
        secretStoreRefs:
          - name: vault
            kind: SecretStore
        selector:
          secret:
            name: my-app-secret
        data:
          - match:
              secretKey: DATABASE_URL
              remoteRef:
                remoteKey: apps/my-app/db
                property: url
```

## Generator resources (v1.1.0+)

### Password generator

Generate random passwords without storing them in an external vault:

```yaml
nuc-external-secrets:
  enabled: true
  generators:
    app-password:
      kind: Password
      spec:
        length: 32
        digits: 5
        symbols: 5
        symbolCharacters: "-_$@"
        noUpper: false
        allowRepeat: false
```

### VaultDynamicSecret generator

Generate short-lived Vault dynamic credentials (database, AWS, PKI):

```yaml
nuc-external-secrets:
  enabled: true
  generators:
    db-creds:
      kind: VaultDynamicSecret
      spec:
        path: database/creds/my-app
        method: GET
        provider:
          server: https://vault.example.com:8200
          auth:
            kubernetes:
              mountPath: kubernetes
              role: my-app
```

Use a generator in an ExternalSecret via `sourceRef`:

```yaml
nuc-external-secrets:
  enabled: true
  externalSecrets:
    app-generated-password:
      spec:
        refreshInterval: 1h
        target:
          name: app-generated-password
          creationPolicy: Owner
        dataFrom:
          - sourceRef:
              generatorRef:
                apiVersion: generators.external-secrets.io/v1alpha1
                kind: Password
                name: app-password
```

### ClusterGenerator

Define a cluster-scoped generator reusable across all namespaces:

```yaml
nuc-external-secrets:
  enabled: true
  clusterGenerators:
    global-ecr:
      kind: ECRAuthorizationToken
      spec:
        region: us-east-1
        auth:
          jwt:
            serviceAccountRef:
              name: external-secrets-sa
              namespace: external-secrets
```

## Best practices

- **Use ClusterSecretStores** for secrets shared across namespaces — avoids duplicating store configuration per namespace.
- **Set `refreshInterval`** based on secret rotation frequency — 1h is a safe default; reduce to 5m for high-rotation dynamic secrets.
- **Use `dataFrom.extract`** to sync all keys from a Vault secret path at once — eliminates per-key mapping when all keys are needed.
- **Use `target.creationPolicy: Owner`** so ESO owns the Kubernetes Secret and garbage-collects it when the ExternalSecret is deleted.
- **Combine with nuc-vault-secret-operator** only if you need different auth flows — prefer one operator per cluster to reduce operational complexity.
- **Use WorkloadIdentity / IRSA** for cloud providers instead of static credentials — eliminates long-lived access keys.
- **Never sync secrets to ConfigMaps** — if a secret value ends up in a ConfigMap it loses Kubernetes RBAC protection.
