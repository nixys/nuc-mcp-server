# nuc-envoy-gateway — Best Practice Guide

**nuc-envoy-gateway** manages Envoy Gateway CRD resources: Backends, BackendTrafficPolicies, ClientTrafficPolicies, SecurityPolicies, EnvoyExtensionPolicies, and EnvoyPatchPolicies.

**Prerequisite:** Envoy Gateway must be installed in the cluster. The subchart manages Envoy Gateway *policy* CRDs — Gateways and HTTPRoutes are managed by nuc-native-gateway.

**Note:** The enable condition for this subchart is `global.nuc-envoy-gateway.enabled`, not `nuc-envoy-gateway.enabled`:

```yaml
global:
  nuc-envoy-gateway:
    enabled: true
```

## Backends (external endpoints)

Register external upstream backends:

```yaml
nuc-envoy-gateway:
  backends:
    external-api:
      spec:
        endpoints:
          - fqdn:
              hostname: api.external.com
              port: 443
        tls:
          wellKnownCACertificates: System   # use system CA bundle
```

## BackendTrafficPolicies

Apply load balancing, circuit breaking, and health checks to backend traffic:

```yaml
nuc-envoy-gateway:
  backendTrafficPolicies:
    api:
      spec:
        targetRefs:
          - group: gateway.networking.k8s.io
            kind: HTTPRoute
            name: api
        loadBalancer:
          type: RoundRobin
        circuitBreaker:
          maxConnections: 1024
          maxPendingRequests: 1024
          maxParallelRequests: 1024
        timeout:
          http:
            requestTimeout: 30s
        retry:
          numRetries: 3
          retryOn:
            triggers:
              - "5xx"
              - "reset"
              - "connect-failure"
          perRetry:
            timeout: 10s
```

## ClientTrafficPolicies

Control how Envoy Gateway handles incoming client connections:

```yaml
nuc-envoy-gateway:
  clientTrafficPolicies:
    edge:
      spec:
        targetRefs:
          - group: gateway.networking.k8s.io
            kind: Gateway
            name: edge
        http:
          http3:
            enabled: true
        connection:
          bufferLimit: 32Mi
        timeout:
          http:
            requestReceivedTimeout: 10s
```

## SecurityPolicies (CORS, JWT, OIDC, Basic Auth)

### CORS

```yaml
nuc-envoy-gateway:
  securityPolicies:
    cors:
      spec:
        targetRefs:
          - group: gateway.networking.k8s.io
            kind: HTTPRoute
            name: api
        cors:
          allowOrigins:
            - "https://app.example.com"
          allowMethods:
            - GET
            - POST
            - PUT
            - DELETE
          allowHeaders:
            - Authorization
            - Content-Type
          maxAge: 3600s
```

### JWT authentication

```yaml
nuc-envoy-gateway:
  securityPolicies:
    jwt-auth:
      spec:
        targetRefs:
          - group: gateway.networking.k8s.io
            kind: HTTPRoute
            name: api
        jwt:
          providers:
            - name: keycloak
              issuer: https://keycloak.example.com/realms/app
              audiences:
                - api-client
              remoteJWKS:
                uri: https://keycloak.example.com/realms/app/protocol/openid-connect/certs
```

### OIDC (Authorization Code Flow)

```yaml
nuc-envoy-gateway:
  securityPolicies:
    oidc:
      spec:
        targetRefs:
          - group: gateway.networking.k8s.io
            kind: Gateway
            name: edge
        oidc:
          provider:
            issuer: https://keycloak.example.com/realms/app
          clientID: gateway-client
          clientSecret:
            name: oidc-client-secret
            namespace: default
          redirectURL: https://app.example.com/oauth2/callback
          logoutPath: /logout
          scopes:
            - openid
            - email
            - profile
```

## EnvoyPatchPolicies (raw xDS patches)

For advanced use cases not covered by standard policies:

```yaml
nuc-envoy-gateway:
  envoyPatchPolicies:
    custom-patch:
      spec:
        targetRef:
          group: gateway.networking.k8s.io
          kind: Gateway
          name: edge
        type: JSONPatch
        jsonPatches:
          - type: "type.googleapis.com/envoy.config.listener.v3.Listener"
            operation:
              op: add
              path: "/filter_chains/0/filters/0/typed_config/http_filters/0"
              value:
                name: "envoy.filters.http.lua"
```

## Best practices

- **Use `global.nuc-envoy-gateway.enabled: true`** (not `nuc-envoy-gateway.enabled`) — the subchart condition key is under `global`.
- **Pair BackendTrafficPolicies with HTTPRoutes** — target the HTTPRoute, not the Gateway, for per-route traffic policies.
- **Use SecurityPolicies for authentication** instead of per-application JWT validation — centralised auth at the gateway reduces duplication.
- **Use OIDC SecurityPolicy** for browser-facing apps that need a full authorization code flow, and JWT SecurityPolicy for API-to-API authentication.
- **Use EnvoyPatchPolicies sparingly** — they bypass the standard API surface and are sensitive to Envoy version upgrades.
- **Combine with nuc-native-gateway** — define Gateways and HTTPRoutes there, then attach BackendTrafficPolicies and SecurityPolicies here.
