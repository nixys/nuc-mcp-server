# nuc-istio — Best Practice Guide

**nuc-istio** manages Istio CRD resources: Gateways, VirtualServices, DestinationRules, ServiceEntries, Sidecars, AuthorizationPolicies, PeerAuthentications, RequestAuthentications, EnvoyFilters, and WorkloadEntries/Groups.

**Prerequisite:** Istio control plane must be installed in the cluster.

## Enable

```yaml
nuc-istio:
  enabled: true
```

## Gateways

Define ingress/egress points for the mesh:

```yaml
nuc-istio:
  enabled: true
  gateways:
    public:
      spec:
        selector:
          istio: ingressgateway
        servers:
          - port:
              number: 443
              name: https
              protocol: HTTPS
            tls:
              mode: SIMPLE
              credentialName: app-tls       # Kubernetes Secret with TLS cert
            hosts:
              - app.example.com
          - port:
              number: 80
              name: http
              protocol: HTTP
            hosts:
              - app.example.com
            tls:
              httpsRedirect: true
```

## VirtualServices

Route traffic to services with weights, retries, timeouts:

```yaml
nuc-istio:
  enabled: true
  virtualservices:
    app:
      spec:
        hosts:
          - app.example.com
        gateways:
          - public
        http:
          - match:
              - uri:
                  prefix: /api
            route:
              - destination:
                  host: app.default.svc.cluster.local
                  port:
                    number: 8080
            timeout: 30s
            retries:
              attempts: 3
              perTryTimeout: 10s
              retryOn: 5xx,reset,connect-failure
```

### Canary / traffic splitting

```yaml
nuc-istio:
  enabled: true
  virtualservices:
    app:
      spec:
        hosts:
          - app.default.svc.cluster.local
        http:
          - route:
              - destination:
                  host: app.default.svc.cluster.local
                  subset: stable
                weight: 90
              - destination:
                  host: app.default.svc.cluster.local
                  subset: canary
                weight: 10
```

## DestinationRules

Configure subsets, load balancing, and circuit breakers:

```yaml
nuc-istio:
  enabled: true
  destinationrules:
    app:
      spec:
        host: app.default.svc.cluster.local
        trafficPolicy:
          connectionPool:
            http:
              h2UpgradePolicy: UPGRADE
          outlierDetection:
            consecutive5xxErrors: 5
            interval: 30s
            baseEjectionTime: 30s
        subsets:
          - name: stable
            labels:
              version: stable
          - name: canary
            labels:
              version: canary
```

### mTLS mode

```yaml
nuc-istio:
  enabled: true
  destinationrules:
    internal:
      spec:
        host: "*.svc.cluster.local"
        trafficPolicy:
          tls:
            mode: ISTIO_MUTUAL
```

## PeerAuthentications (mTLS policy)

```yaml
nuc-istio:
  enabled: true
  peerauthentications:
    default:
      spec:
        mtls:
          mode: STRICT           # enforce mTLS for all pods in namespace
```

## AuthorizationPolicies

```yaml
nuc-istio:
  enabled: true
  authorizationpolicies:
    allow-frontend:
      spec:
        selector:
          matchLabels:
            app: backend
        action: ALLOW
        rules:
          - from:
              - source:
                  principals:
                    - cluster.local/ns/default/sa/frontend
```

## ServiceEntries (external services)

Register external services in the mesh:

```yaml
nuc-istio:
  enabled: true
  serviceentries:
    external-api:
      spec:
        hosts:
          - api.external.com
        ports:
          - number: 443
            name: https
            protocol: HTTPS
        resolution: DNS
        location: MESH_EXTERNAL
```

## Egress gateway

```yaml
nuc-istio:
  enabled: true
  gateways:
    egress:
      spec:
        selector:
          istio: egressgateway
        servers:
          - port:
              number: 443
              name: https
              protocol: HTTPS
            hosts:
              - api.external.com
            tls:
              mode: PASSTHROUGH
  virtualservices:
    egress-external:
      spec:
        hosts:
          - api.external.com
        gateways:
          - mesh
          - egress
        http:
          - match:
              - gateways:
                  - mesh
                port: 80
            route:
              - destination:
                  host: istio-egressgateway.istio-system.svc.cluster.local
                  port:
                    number: 80
```

## Sidecars

Limit sidecar scope for performance:

```yaml
nuc-istio:
  enabled: true
  sidecars:
    app:
      spec:
        workloadSelector:
          labels:
            app: my-app
        egress:
          - hosts:
              - "./*"
              - "istio-system/*"
```

## Best practices

- **Enable `STRICT` mTLS** at the namespace level with PeerAuthentication and add a `DestinationRule` for `*.svc.cluster.local` with `ISTIO_MUTUAL` TLS mode.
- **Use retries and timeouts in VirtualServices** instead of relying on application-level retry logic.
- **Limit sidecar egress** with Sidecar resources in busy namespaces — it reduces xDS config size and speeds up Envoy synchronisation.
- **Prefer `MESH_EXTERNAL` ServiceEntries** for external calls that need Istio telemetry and policy instead of bypassing the mesh.
- **Combine with AuthorizationPolicies** to implement zero-trust: deny all by default, then allow only necessary service-to-service paths.
- **Use `httpsRedirect: true`** on the HTTP listener in the Gateway instead of a separate middleware redirect.
