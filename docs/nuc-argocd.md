# nuc-argocd — Best Practice Guide

**nuc-argocd** manages Argo CD CRD resources: Applications, ApplicationSets, and AppProjects.

**Prerequisite:** Argo CD must be installed in the cluster.

## Enable

```yaml
nuc-argocd:
  enabled: true
```

## Applications

### Minimal Application (Git)

```yaml
nuc-argocd:
  enabled: true
  applications:
    my-app:
      spec:
        project: default
        source:
          repoURL: https://github.com/my-org/my-app.git
          targetRevision: HEAD
          path: helm/my-app
        destination:
          server: https://kubernetes.default.svc
          namespace: my-app
        syncPolicy:
          automated:
            prune: true
            selfHeal: true
          syncOptions:
            - CreateNamespace=true
```

### Application from Helm chart registry

```yaml
nuc-argocd:
  enabled: true
  applications:
    nginx:
      spec:
        project: default
        source:
          repoURL: https://charts.bitnami.com/bitnami
          chart: nginx
          targetRevision: 15.x.x
          helm:
            releaseName: nginx
            values: |
              replicaCount: 2
        destination:
          server: https://kubernetes.default.svc
          namespace: nginx
        syncPolicy:
          automated:
            prune: true
            selfHeal: true
          syncOptions:
            - CreateNamespace=true
```

### Multi-source Application (values override from separate repo)

```yaml
nuc-argocd:
  enabled: true
  applications:
    my-app-prod:
      spec:
        project: production
        sources:
          - repoURL: oci://registry.example.com/charts
            chart: my-app
            targetRevision: 1.2.3
            helm:
              valueFiles:
                - $values/envs/prod/values.yaml
          - repoURL: https://github.com/my-org/gitops.git
            targetRevision: main
            ref: values
        destination:
          server: https://kubernetes.default.svc
          namespace: my-app-prod
        syncPolicy:
          automated:
            prune: true
            selfHeal: true
```

## ApplicationSets

### Git generator (one Application per directory)

```yaml
nuc-argocd:
  enabled: true
  applicationSets:
    apps:
      spec:
        generators:
          - git:
              repoURL: https://github.com/my-org/gitops.git
              revision: HEAD
              directories:
                - path: apps/*
        template:
          metadata:
            name: "{{path.basename}}"
          spec:
            project: default
            source:
              repoURL: https://github.com/my-org/gitops.git
              targetRevision: HEAD
              path: "{{path}}"
            destination:
              server: https://kubernetes.default.svc
              namespace: "{{path.basename}}"
            syncPolicy:
              automated:
                prune: true
                selfHeal: true
              syncOptions:
                - CreateNamespace=true
```

### Cluster generator (deploy to all clusters)

```yaml
nuc-argocd:
  enabled: true
  applicationSets:
    cluster-addons:
      spec:
        generators:
          - clusters: {}
        template:
          metadata:
            name: "cluster-addons-{{name}}"
          spec:
            project: default
            source:
              repoURL: https://github.com/my-org/gitops.git
              targetRevision: HEAD
              path: cluster-addons
            destination:
              server: "{{server}}"
              namespace: kube-system
            syncPolicy:
              automated:
                prune: true
                selfHeal: true
```

## AppProjects

### Restricted project for a team

```yaml
nuc-argocd:
  enabled: true
  appProjects:
    team-alpha:
      spec:
        description: "Resources for team-alpha"
        sourceRepos:
          - https://github.com/my-org/team-alpha.git
          - oci://registry.example.com/charts
        destinations:
          - namespace: team-alpha-*
            server: https://kubernetes.default.svc
        clusterResourceWhitelist:
          - group: ""
            kind: Namespace
        namespaceResourceBlacklist:
          - group: ""
            kind: ResourceQuota
        roles:
          - name: developer
            description: "Read-only access for developers"
            policies:
              - p, proj:team-alpha:developer, applications, get, team-alpha/*, allow
              - p, proj:team-alpha:developer, applications, sync, team-alpha/*, allow
            groups:
              - github-team-alpha
```

## Best practices

- **Use `syncPolicy.automated` with `selfHeal: true`** to prevent configuration drift — Argo CD reconciles back to the desired state automatically.
- **Enable `prune: true`** only after confirming the source repo is the single source of truth — it deletes resources removed from Git.
- **Always set `CreateNamespace=true` in `syncOptions`** for new Applications so Argo CD creates the target namespace if missing.
- **Use AppProjects to scope teams** — restrict `sourceRepos` and `destinations` per project; never give all teams access to the default project in production.
- **Prefer multi-source Applications** over patching chart values inline — keep values in a separate gitops repo and reference with `$values` ref for clean separation.
- **Use ApplicationSets with Git generator** for large monorepos — one ApplicationSet manages all apps under a directory tree without per-app YAML.
- **Set `syncPolicy.retry`** with backoff for apps that depend on CRDs being installed first:
  ```yaml
  syncPolicy:
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  ```
