# nuc-vault-secret-operator — Best Practice Guide

**nuc-vault-secret-operator** manages Vault Secret Operator CRD resources: VaultConnections, VaultAuths, VaultStaticSecrets, VaultDynamicSecrets, VaultPKISecrets, and VaultAuthGlobals.

**Prerequisite:** Vault Secret Operator (VSO by HashiCorp) must be installed in the cluster, and a HashiCorp Vault instance must be accessible.

## Enable

```yaml
nuc-vault-secret-operator:
  enabled: true
```

## VaultConnections

Define connection parameters to a Vault instance:

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultConnections:
    default:
      spec:
        address: https://vault.example.com:8200
        caCertSecretRef:
          name: vault-ca-cert     # optional: custom CA bundle
        skipTLSVerify: false
```

## VaultAuths

Authenticate to Vault using Kubernetes service accounts:

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultAuths:
    app:
      spec:
        vaultConnectionRef: default
        method: kubernetes
        mount: kubernetes
        kubernetes:
          role: my-app
          serviceAccount: default    # Kubernetes ServiceAccount to use for JWT auth
          audiences:
            - vault
```

### AppRole authentication

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultAuths:
    approle:
      spec:
        vaultConnectionRef: default
        method: appRole
        mount: approle
        appRole:
          roleId: my-role-id
          secretRef:
            name: vault-approle-secret
            key: secret-id
```

## VaultStaticSecrets

Sync static KV secrets from Vault into Kubernetes Secrets:

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultStaticSecrets:
    app-config:
      spec:
        vaultAuthRef: app
        mount: secret
        type: kv-v2
        path: apps/my-app/config
        destination:
          name: app-config         # Kubernetes Secret name
          create: true
        refreshAfter: 1h
```

### Map specific fields

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultStaticSecrets:
    db-credentials:
      spec:
        vaultAuthRef: app
        mount: secret
        type: kv-v2
        path: apps/my-app/db
        destination:
          name: db-credentials
          create: true
        hmacSecretData: true
        transformationRefs: []
```

## VaultDynamicSecrets

Generate short-lived dynamic secrets (database credentials, AWS credentials):

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultDynamicSecrets:
    db-creds:
      spec:
        vaultAuthRef: app
        mount: database
        path: creds/my-app-role
        destination:
          name: db-creds
          create: true
        rolloutRestartTargets:
          - kind: Deployment
            name: api             # restart the Deployment when credentials rotate
        renewalPercent: 67        # renew when 67% of the TTL has elapsed
```

### AWS dynamic credentials

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultDynamicSecrets:
    aws-creds:
      spec:
        vaultAuthRef: app
        mount: aws
        path: creds/my-app-role
        destination:
          name: aws-creds
          create: true
        renewalPercent: 67
```

## VaultPKISecrets

Issue short-lived TLS certificates from Vault PKI:

```yaml
nuc-vault-secret-operator:
  enabled: true
  vaultPKISecrets:
    app-tls:
      spec:
        vaultAuthRef: app
        mount: pki
        role: my-app-tls
        commonName: app.example.com
        altNames:
          - api.example.com
        ttl: 72h
        destination:
          name: app-tls
          create: true
        rolloutRestartTargets:
          - kind: Deployment
            name: api
```

## Best practices

- **Always define VaultConnections and VaultAuths** as separate resources — this decouples connectivity and authentication, making it easier to rotate credentials or switch auth methods.
- **Use Kubernetes auth method** (not AppRole or Token) for in-cluster workloads — it uses the pod's ServiceAccount JWT, which rotates automatically.
- **Set `rolloutRestartTargets`** on VaultDynamicSecrets and VaultPKISecrets — VSO will restart the target Deployment when credentials rotate, ensuring pods always use fresh credentials.
- **Use VaultDynamicSecrets for database access** — short-lived database credentials (TTL 1–24h) significantly reduce the blast radius of a credential leak.
- **Set `renewalPercent: 67`** — VSO renews when 67% of the lease has elapsed, leaving a safety window for retries before the secret expires.
- **Avoid VaultStaticSecrets with long-lived tokens** — if the token is compromised, it can be used until the next rotation. Prefer dynamic secrets or PKI when available.
- **Reference generated Secrets in workloads** via `envSecrets` in the root chart `deployments.<name>.containers.<name>.envSecrets`.
