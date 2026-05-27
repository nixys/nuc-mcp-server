# nuc-fluxcd — Best Practice Guide

**nuc-fluxcd** manages Flux CD CRD resources: GitRepositories, OCIRepositories, HelmRepositories, HelmCharts, Kustomizations, HelmReleases, ImageRepositories, ImagePolicies, and ImageUpdateAutomations.

**Prerequisite:** Flux CD must be installed in the cluster (bootstrap via `flux bootstrap`).

## Enable

```yaml
nuc-fluxcd:
  enabled: true
```

## GitRepositories

```yaml
nuc-fluxcd:
  enabled: true
  gitRepositories:
    app:
      spec:
        interval: 1m
        url: https://github.com/my-org/my-app-config.git
        ref:
          branch: main
        secretRef:
          name: github-credentials    # Secret with: username, password (or deploy key)
```

### SSH key authentication

```yaml
nuc-fluxcd:
  enabled: true
  gitRepositories:
    platform:
      spec:
        interval: 1m
        url: ssh://git@github.com/my-org/platform.git
        ref:
          branch: main
        secretRef:
          name: github-deploy-key    # Secret with: identity, identity.pub, known_hosts
```

## OCIRepositories

```yaml
nuc-fluxcd:
  enabled: true
  ociRepositories:
    app-config:
      spec:
        interval: 5m
        url: oci://registry.example.com/my-org/app-config
        ref:
          tag: latest
        secretRef:
          name: registry-credentials
```

## HelmRepositories

```yaml
nuc-fluxcd:
  enabled: true
  helmRepositories:
    bitnami:
      spec:
        interval: 30m
        url: https://charts.bitnami.com/bitnami
    nixys-oci:
      spec:
        interval: 30m
        type: oci
        url: oci://registry.nixys.ru/nuc
```

## Kustomizations

```yaml
nuc-fluxcd:
  enabled: true
  kustomizations:
    app:
      spec:
        interval: 5m
        path: ./clusters/dev
        prune: true
        sourceRef:
          kind: GitRepository
          name: app
        healthChecks:
          - apiVersion: apps/v1
            kind: Deployment
            name: api
            namespace: default
        postBuild:
          substituteFrom:
            - kind: ConfigMap
              name: cluster-vars
            - kind: Secret
              name: cluster-secrets
```

### Dependency ordering

```yaml
nuc-fluxcd:
  enabled: true
  kustomizations:
    infra:
      spec:
        interval: 10m
        path: ./infra
        prune: true
        sourceRef:
          kind: GitRepository
          name: platform
    apps:
      spec:
        interval: 5m
        path: ./apps
        prune: true
        sourceRef:
          kind: GitRepository
          name: platform
        dependsOn:
          - name: infra              # apps are deployed only after infra is healthy
```

## HelmReleases

```yaml
nuc-fluxcd:
  enabled: true
  helmReleases:
    my-app:
      spec:
        interval: 10m
        chart:
          spec:
            chart: my-app
            version: ">=1.0.0 <2.0.0"
            sourceRef:
              kind: HelmRepository
              name: my-repo
            interval: 1m
        values:
          replicaCount: 2
          image:
            tag: "1.2.3"
        valuesFrom:
          - kind: Secret
            name: my-app-values
            valuesKey: values.yaml
        install:
          remediation:
            retries: 3
        upgrade:
          remediation:
            retries: 3
            remediateLastFailure: true
          cleanupOnFail: true
        rollback:
          timeout: 5m
          cleanupOnFail: true
```

## Image automation

### ImageRepository

```yaml
nuc-fluxcd:
  enabled: true
  imageRepositories:
    app:
      spec:
        image: registry.example.com/my-org/my-app
        interval: 5m
        secretRef:
          name: registry-credentials
```

### ImagePolicy

```yaml
nuc-fluxcd:
  enabled: true
  imagePolicies:
    app:
      spec:
        imageRepositoryRef:
          name: app
        policy:
          semver:
            range: ">=1.0.0 <2.0.0"
```

### ImageUpdateAutomation

```yaml
nuc-fluxcd:
  enabled: true
  imageUpdateAutomations:
    app:
      spec:
        interval: 5m
        sourceRef:
          kind: GitRepository
          name: app
        git:
          checkout:
            ref:
              branch: main
          commit:
            author:
              name: Flux
              email: flux@example.com
            messageTemplate: "chore: update app image to {{range .Updated.Images}}{{.}}{{end}}"
          push:
            branch: main
        update:
          strategy: Setters
          path: ./clusters/dev
```

## Best practices

- **Use `interval: 1m`** on GitRepositories and `interval: 5m`** on Kustomizations — Flux polls frequently by default; this is a safe baseline.
- **Use `prune: true`** on Kustomizations — it removes resources that are no longer in Git, keeping cluster state in sync.
- **Use `dependsOn`** to order Kustomization reconciliation — deploy infrastructure (CRDs, operators) before application workloads.
- **Use `healthChecks`** in Kustomizations — Flux waits for the checked resources to become ready before marking the Kustomization healthy and unblocking dependents.
- **Use `valuesFrom` in HelmReleases** to inject secrets without embedding them in values — the Secret content is merged with the inline `values` block.
- **Enable remediation in HelmReleases** (`install.remediation.retries`, `upgrade.remediation.retries`) — Flux retries failed installs and upgrades automatically.
- **Use `gitops.flux.enabled: true`** in the root chart to add Flux-specific labels/annotations to all rendered resources.
