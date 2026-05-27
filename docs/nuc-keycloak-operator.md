# nuc-keycloak-operator — Best Practice Guide

**nuc-keycloak-operator** manages Keycloak Operator CRD resources: Keycloaks, KeycloakRealms, KeycloakClients, KeycloakUsers, and KeycloakRealmImports.

**Prerequisite:** Keycloak Operator must be installed in the cluster.

## Enable

```yaml
nuc-keycloak-operator:
  enabled: true
```

## Keycloaks

### Minimal development instance

```yaml
nuc-keycloak-operator:
  enabled: true
  keycloaks:
    main:
      spec:
        instances: 1
        db:
          vendor: postgres
          host: app-db-rw.default.svc.cluster.local
          database: keycloak
          usernameSecret:
            name: keycloak-db-credentials
            key: username
          passwordSecret:
            name: keycloak-db-credentials
            key: password
        http:
          tlsSecret: keycloak-tls
        hostname:
          hostname: auth.example.com
```

### Production HA instance

```yaml
nuc-keycloak-operator:
  enabled: true
  keycloaks:
    main:
      spec:
        instances: 3
        db:
          vendor: postgres
          host: app-db-rw.default.svc.cluster.local
          database: keycloak
          usernameSecret:
            name: keycloak-db-credentials
            key: username
          passwordSecret:
            name: keycloak-db-credentials
            key: password
        http:
          tlsSecret: keycloak-tls
        hostname:
          hostname: auth.example.com
          adminHostname: auth-admin.internal.example.com
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 2
            memory: 4Gi
        additionalOptions:
          - name: cache
            value: ispn
          - name: cache-stack
            value: kubernetes
```

## KeycloakRealms

```yaml
nuc-keycloak-operator:
  enabled: true
  keycloakRealms:
    app:
      spec:
        keycloakCRName: main
        realm:
          realm: app
          enabled: true
          displayName: "My Application"
          loginTheme: my-theme
          emailTheme: my-theme
          defaultLocale: en
          internationalizationEnabled: true
          supportedLocales:
            - en
            - ru
          loginWithEmailAllowed: true
          duplicateEmailsAllowed: false
          resetPasswordAllowed: true
          editUsernameAllowed: false
          bruteForceProtected: true
          permanentLockout: false
          maxFailureWaitSeconds: 900
          waitIncrementSeconds: 60
          quickLoginCheckMilliSeconds: 1000
          maxDeltaTimeSeconds: 43200
          failureFactor: 10
          sslRequired: external
```

## KeycloakClients

```yaml
nuc-keycloak-operator:
  enabled: true
  keycloakClients:
    app-frontend:
      spec:
        keycloakCRName: main
        client:
          clientId: app-frontend
          name: "Application Frontend"
          enabled: true
          publicClient: true          # no client secret (SPA)
          redirectUris:
            - https://app.example.com/*
          webOrigins:
            - https://app.example.com
          standardFlowEnabled: true
          implicitFlowEnabled: false
          directAccessGrantsEnabled: false
          protocol: openid-connect
    app-backend:
      spec:
        keycloakCRName: main
        client:
          clientId: app-backend
          name: "Application Backend (M2M)"
          enabled: true
          publicClient: false         # confidential client with secret
          serviceAccountsEnabled: true
          standardFlowEnabled: false
          directAccessGrantsEnabled: false
          protocol: openid-connect
          secret: app-backend-client-secret   # referenced Kubernetes Secret
```

## KeycloakUsers

```yaml
nuc-keycloak-operator:
  enabled: true
  keycloakUsers:
    admin:
      spec:
        keycloakCRName: main
        realmSelector:
          matchLabels:
            realm: app
        user:
          username: admin
          email: admin@example.com
          firstName: Admin
          lastName: User
          enabled: true
          emailVerified: true
          credentials:
            - type: password
              secretData: '{"value":"${PASSWORD_HASH}"}'
              credentialData: '{"hashIterations":210000,"algorithm":"pbkdf2-sha512"}'
          realmRoles:
            - default-roles-app
          clientRoles:
            app-backend:
              - admin
```

## Best practices

- **Use CloudNativePG (nuc-cloudnativepg) as the Keycloak database** — PostgreSQL is the recommended production database; avoid embedded H2.
- **Use 3 instances** in production and set `cache-stack: kubernetes` for JGroups-based session clustering without multicast.
- **Store database credentials in Kubernetes Secrets** referenced by `usernameSecret` and `passwordSecret` — manage them with nuc-vault-secret-operator.
- **Use `publicClient: true`** for SPAs (React, Vue) and `publicClient: false` with `serviceAccountsEnabled: true` for backend service-to-service (M2M) clients.
- **Configure Realm brute-force protection** — enable `bruteForceProtected: true` and set appropriate thresholds to limit credential stuffing.
- **Set `sslRequired: external`** (not `all`) to allow internal cluster traffic over plain HTTP while requiring TLS for external connections.
- **Use KeycloakRealmImports** for complex realm configurations that exceed what can be expressed in the KeycloakRealm CRD — import a full realm JSON export.
