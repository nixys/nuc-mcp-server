# nuc-native-gateway — Best Practice Guide

**nuc-native-gateway** manages Kubernetes Gateway API CRD resources: GatewayClasses, Gateways, HTTPRoutes, GRPCRoutes, TLSRoutes, ReferenceGrants, BackendTLSPolicies, and ListenerSets.

**Prerequisite:** A Gateway API-compatible controller (NGINX Gateway Fabric, Istio, Envoy Gateway, Cilium, etc.) must be installed with the standard Gateway API CRDs.

## Enable

```yaml
nuc-native-gateway:
  enabled: true
```

## Gateways

```yaml
nuc-native-gateway:
  enabled: true
  gateways:
    edge:
      spec:
        gatewayClassName: nginx       # or istio, cilium, envoy-gateway
        listeners:
          - name: http
            port: 80
            protocol: HTTP
            hostname: "*.example.com"
          - name: https
            port: 443
            protocol: HTTPS
            hostname: "*.example.com"
            tls:
              mode: Terminate
              certificateRefs:
                - name: wildcard-tls   # Kubernetes Secret
```

## HTTPRoutes

Route HTTP traffic to backend services:

```yaml
nuc-native-gateway:
  enabled: true
  httpRoutes:
    app:
      spec:
        parentRefs:
          - name: edge
            sectionName: https
        hostnames:
          - app.example.com
        rules:
          - matches:
              - path:
                  type: PathPrefix
                  value: /api
            backendRefs:
              - name: api
                port: 8080
          - matches:
              - path:
                  type: PathPrefix
                  value: /
            backendRefs:
              - name: frontend
                port: 80
```

### Traffic splitting (canary)

```yaml
nuc-native-gateway:
  enabled: true
  httpRoutes:
    app-split:
      spec:
        parentRefs:
          - name: edge
        hostnames:
          - app.example.com
        rules:
          - backendRefs:
              - name: app-stable
                port: 8080
                weight: 90
              - name: app-canary
                port: 8080
                weight: 10
```

### Header-based routing

```yaml
nuc-native-gateway:
  enabled: true
  httpRoutes:
    app-internal:
      spec:
        parentRefs:
          - name: edge
        hostnames:
          - app.example.com
        rules:
          - matches:
              - headers:
                  - name: X-Internal
                    value: "true"
            backendRefs:
              - name: app-internal
                port: 8080
          - backendRefs:
              - name: app
                port: 8080
```

## GRPCRoutes

```yaml
nuc-native-gateway:
  enabled: true
  grpcRoutes:
    grpc-api:
      spec:
        parentRefs:
          - name: edge
        hostnames:
          - grpc.example.com
        rules:
          - matches:
              - method:
                  service: myorg.MyService
            backendRefs:
              - name: grpc-server
                port: 50051
```

## TLSRoutes (passthrough)

```yaml
nuc-native-gateway:
  enabled: true
  tlsRoutes:
    postgres:
      spec:
        parentRefs:
          - name: edge
            sectionName: tls-passthrough
        hostnames:
          - db.example.com
        rules:
          - backendRefs:
              - name: postgres
                port: 5432
```

## ReferenceGrants (cross-namespace)

Allow a Gateway in namespace `infra` to reference a Service in namespace `app`:

```yaml
nuc-native-gateway:
  enabled: true
  referenceGrants:
    allow-infra-to-app:
      spec:
        from:
          - group: gateway.networking.k8s.io
            kind: HTTPRoute
            namespace: infra
        to:
          - group: ""
            kind: Service
            namespace: app
```

## GatewayClasses

Define a custom gateway class for a controller that doesn't ship its own:

```yaml
nuc-native-gateway:
  enabled: true
  gatewayClasses:
    my-controller:
      spec:
        controllerName: example.com/my-gateway-controller
        description: "Custom gateway class managed by my-controller"
```

## BackendTLSPolicies

Enforce TLS from the Gateway to backend Pods (end-to-end encryption):

```yaml
nuc-native-gateway:
  enabled: true
  backendTLSPolicies:
    backend-tls:
      spec:
        targetRefs:
          - group: ""
            kind: Service
            name: api
        validation:
          caCertificateRefs:
            - group: ""
              kind: ConfigMap
              name: backend-ca
          hostname: api.internal.example.com
```

## ListenerSets

Group listeners across multiple Gateways for shared configuration (Gateway API v1.3+):

```yaml
nuc-native-gateway:
  enabled: true
  listenerSets:
    shared-listeners:
      spec:
        parentRef:
          name: edge
        listeners:
          - name: http
            port: 80
            protocol: HTTP
          - name: https
            port: 443
            protocol: HTTPS
            tls:
              mode: Terminate
              certificateRefs:
                - name: wildcard-tls
```

## Best practices

- **Use `sectionName`** in `parentRefs` to bind an HTTPRoute to a specific listener (e.g., `https` only) instead of all listeners on the Gateway.
- **Terminate TLS at the Gateway**, not at individual service pods, unless end-to-end encryption is required.
- **Use BackendTLSPolicy** to enforce mTLS between the Gateway and backend Pods — prevents eavesdropping on intra-cluster traffic.
- **Use ReferenceGrants** explicitly for any cross-namespace backend references — the Gateway API requires explicit permission.
- **Prefer GRPCRoute over HTTPRoute** for gRPC services — it provides method-level matching without managing path patterns manually.
- **Combine with nuc-certificates** — reference the cert-manager-issued Secret in the Gateway's `tls.certificateRefs`.
- **Match `gatewayClassName`** to the actual controller installed in the cluster — mismatched class names silently leave routes unbound.
- **Use ListenerSets** to share listener definitions across Gateways — reduces duplication when multiple Gateways share the same port/protocol/TLS config.
