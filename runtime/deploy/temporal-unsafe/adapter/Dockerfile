# syntax=docker/dockerfile:1.7

ARG GO_IMAGE=docker.io/library/golang:1.25.13-alpine@sha256:844b27705f54e73773e0f9bc3c780633b9d7f4b4831bf35cdad02a81a4c80bd0
ARG RUNTIME_IMAGE=docker.io/library/alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412

FROM ${GO_IMAGE} AS build
WORKDIR /src/runtime
COPY runtime/go.mod runtime/go.sum ./
RUN go mod download
COPY runtime/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -buildid=" \
    -o /out/temporal-provider-adapter ./deploy/temporal-unsafe/adapter

FROM ${RUNTIME_IMAGE}
ARG GIT_REVISION=unknown
ARG SOURCE_SHA256=unknown
ARG RUNTIME_IMAGE
LABEL org.opencontainers.image.title="safe-change Temporal provider adapter" \
      org.opencontainers.image.source="https://github.com/eunomia-bpf/agent-check-restore-safety" \
      org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.base.name="${RUNTIME_IMAGE}" \
      io.safe-change.source.sha256="${SOURCE_SHA256}"
RUN apk add --no-cache ca-certificates && \
    addgroup -S -g 65532 safechange && \
    adduser -S -D -H -u 65532 -G safechange safechange
COPY --from=build --chmod=0555 /out/temporal-provider-adapter /usr/local/bin/temporal-provider-adapter
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/temporal-provider-adapter"]
