# nuc-traefik — Best Practice Guide

**nuc-traefik** manages Traefik CRD resources: IngressRoutes, Middlewares, TLSStores, ServersTransports, TraefikServices, and IngressRouteTCPs/UDPs.

**Prerequisite:** Traefik must be installed in the cluster (the subchart does not install Traefik itself — it only manages its CRDs).

## Enable

```yaml
nuc-traefik:
  enabled: true
```

## IngressRoutes

Route HTTP/HTTPS traffic to backend services:

```yaml
nuc-traefik:
  enabled: true
  ingressRoutes:
    web:
      enabled: true
      name: web
      spec:
        entryPoints:
          - websecure
        routes:
          - match: Host(`app.example.com`)
            kind: Rule
            services:
              - name: app
                port: 8080
            middlewares:
              - name: auth
        tls:
          certResolver: letsencrypt
```

## Middlewares

Apply authentication, rate limiting, headers, redirects:

```yaml
nuc-traefik:
  enabled: true
  middlewares:
    auth:
      spec:
        basicAuth:
          secret: auth-credentials
    redirect-https:
      spec:
        redirectScheme:
          scheme: https
          permanent: true
    rate-limit:
      spec:
        rateLimit:
          average: 100
          burst: 50
    strip-prefix:
      spec:
        stripPrefix:
          prefixes:
            - /api
```

## TLS configuration

### TLSStores (global default TLS cert)

```yaml
nuc-traefik:
  enabled: true
  tlsStores:
    default:
      spec:
        defaultCertificate:
          secretName: wildcard-tls
```

### TLSOptions

```yaml
nuc-traefik:
  enabled: true
  tlsOptions:
    strict:
      spec:
        minVersion: VersionTLS12
        cipherSuites:
          - TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
          - TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305
        sniStrict: true
```

## TCP routing

```yaml
nuc-traefik:
  enabled: true
  ingressRouteTCPs:
    postgres:
      spec:
        entryPoints:
          - postgres
        routes:
          - match: HostSNI(`db.example.com`)
            services:
              - name: postgres
                port: 5432
        tls:
          passthrough: true
```

## ServersTransports (mTLS to backend)

```yaml
nuc-traefik:
  enabled: true
  serversTransports:
    secure-backend:
      spec:
        serverName: backend.internal
        rootCAsSecrets:
          - backend-ca
        certificates:
          - secretName: client-cert
```

## TraefikServices (load balancing / mirroring)

```yaml
nuc-traefik:
  enabled: true
  traefikServices:
    weighted:
      spec:
        weighted:
          services:
            - name: app-v1
              port: 8080
              weight: 80
            - name: app-v2
              port: 8080
              weight: 20
```

## Best practices

- **Use named middlewares** and reference them across multiple IngressRoutes instead of duplicating config.
- **Combine with nuc-certificates** — set `tls.secretName` in the IngressRoute and let cert-manager issue the certificate automatically.
- **Use `ingressRouteTCPs` with `passthrough: true`** for databases — Traefik passes TLS through to the backend instead of terminating it.
- **Never expose raw HTTP in production** — add the `redirect-https` middleware to the `web` entrypoint or configure a `redirections` entry in Traefik's static config.
- **Use TLSStores `default`** for a global wildcard certificate fallback so all routes get TLS even when no explicit cert is specified.
