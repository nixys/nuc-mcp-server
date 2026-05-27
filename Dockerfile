FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./

RUN pip install --upgrade pip wheel
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels --no-deps .


FROM debian:bookworm-slim AS helm

ARG HELM_VERSION=3.18.4
ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tar \
    && rm -rf /var/lib/apt/lists/*

RUN case "${TARGETARCH}" in \
      amd64) helm_arch="amd64" ;; \
      arm64) helm_arch="arm64" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && cd /tmp \
    && curl -fsSL "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${helm_arch}.tar.gz" \
         -o "helm-v${HELM_VERSION}-linux-${helm_arch}.tar.gz" \
    && curl -fsSL "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${helm_arch}.tar.gz.sha256sum" \
         -o helm.sha256sum \
    && sha256sum -c helm.sha256sum \
    && tar -xzf "helm-v${HELM_VERSION}-linux-${helm_arch}.tar.gz" \
    && mv "linux-${helm_arch}/helm" /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm


FROM python:3.12-slim AS runtime

ARG UID=10001
ARG GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:${PATH}" \
    NUC_ROOT_CHART_GIT_URL=https://github.com/nixys/nxs-universal-chart.git \
    NUC_ROOT_CHART_GIT_REF=v3.1.0 \
    NUC_REMOTE_CACHE_DIR=/tmp/nuc-chart-mcp-cache

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${GID}" nuc \
    && useradd --uid "${UID}" --gid "${GID}" --create-home --home-dir /home/nuc --shell /usr/sbin/nologin nuc \
    && python -m venv /opt/venv

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY --from=helm /usr/local/bin/helm /usr/local/bin/helm

RUN mkdir -p /tmp/nuc-chart-mcp-cache \
    && chown -R nuc:nuc /app /opt/venv /home/nuc /tmp/nuc-chart-mcp-cache

USER nuc

EXPOSE 8080

ENTRYPOINT ["nuc-chart-mcp", "--transport", "http", "--bind", "0.0.0.0", "--port", "8080", "--http-path", "/mcp"]
