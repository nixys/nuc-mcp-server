# nuc-certificates — Best Practice Guide

**nuc-certificates** manages cert-manager CRD resources: ClusterIssuers, Issuers, Certificates, and CertificateRequests.

**Prerequisite:** cert-manager must be installed in the cluster.

## Enable

```yaml
nuc-certificates:
  enabled: true
```

## ClusterIssuers

### ACME / Let's Encrypt (HTTP-01)

```yaml
nuc-certificates:
  enabled: true
  clusterIssuers:
    letsencrypt:
      spec:
        acme:
          email: ops@example.com
          server: https://acme-v02.api.letsencrypt.org/directory
          privateKeySecretRef:
            name: letsencrypt-account-key
          solvers:
            - http01:
                ingress:
                  ingressClassName: nginx
```

### ACME / Let's Encrypt (DNS-01)

```yaml
nuc-certificates:
  enabled: true
  clusterIssuers:
    letsencrypt-dns:
      spec:
        acme:
          email: ops@example.com
          server: https://acme-v02.api.letsencrypt.org/directory
          privateKeySecretRef:
            name: letsencrypt-dns-account-key
          solvers:
            - dns01:
                cloudflare:
                  email: ops@example.com
                  apiTokenSecretRef:
                    name: cloudflare-api-token
                    key: api-token
```

### Self-signed (development)

```yaml
nuc-certificates:
  enabled: true
  clusterIssuers:
    selfsigned:
      spec:
        selfSigned: {}
```

### Internal CA

```yaml
nuc-certificates:
  enabled: true
  clusterIssuers:
    internal-ca:
      spec:
        ca:
          secretName: internal-ca-tls
```

## Namespaced Issuers

```yaml
nuc-certificates:
  enabled: true
  issuers:
    app-issuer:
      spec:
        ca:
          secretName: app-ca-tls
```

## Certificates

```yaml
nuc-certificates:
  enabled: true
  certificates:
    api-tls:
      spec:
        secretName: api-tls
        issuerRef:
          name: letsencrypt
          kind: ClusterIssuer
        commonName: api.example.com
        dnsNames:
          - api.example.com
          - www.api.example.com
        duration: 2160h    # 90 days
        renewBefore: 360h  # renew 15 days before expiry
```

### Wildcard certificate

```yaml
nuc-certificates:
  enabled: true
  certificates:
    wildcard-tls:
      spec:
        secretName: wildcard-tls
        issuerRef:
          name: letsencrypt-dns
          kind: ClusterIssuer
        commonName: "*.example.com"
        dnsNames:
          - "*.example.com"
          - example.com
```

## Best practices

- **Staging first** — use `https://acme-staging-v02.api.letsencrypt.org/directory` for testing to avoid Let's Encrypt rate limits. Switch to production only after verifying the full chain works.
- **Prefer DNS-01** for wildcard certificates or clusters without a public ingress (internal or private clusters).
- **Set `renewBefore`** to at least 360h (15 days) so cert-manager has time to retry if the ACME challenge fails.
- **Use ClusterIssuers** (not namespaced Issuers) for certificates shared across namespaces (e.g., wildcard TLS used by Traefik TLSStore).
- **Reference issued certs in workloads** via `envSecrets` or `volumes[].secret.secretName` in the root chart, not by hardcoding secret names in the subchart.
- **Combine with nuc-traefik** — set `tls.secretName` in IngressRoutes to the same `secretName` used in the Certificate spec; cert-manager populates the secret automatically.
