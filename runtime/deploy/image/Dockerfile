# syntax=docker/dockerfile:1.7

ARG GO_IMAGE=docker.io/library/golang:1.25.4-alpine3.22@sha256:d3f0cf7723f3429e3f9ed846243970b20a2de7bae6a5b66fc5914e228d831bbb
ARG RUNTIME_IMAGE=docker.io/library/alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412

FROM ${GO_IMAGE} AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -buildid=" -o /out/control ./cmd/control && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -buildid=" -o /out/safe-change ./cmd/safe-change && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -buildid=" -o /out/effect-proxy ./cmd/effect-proxy && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -buildid=" -o /out/check-certificate ./cmd/check-certificate

FROM ${RUNTIME_IMAGE}

ARG VERSION=dev
ARG REVISION=unknown
ARG RUNTIME_IMAGE
LABEL org.opencontainers.image.title="safe-change runtime" \
      org.opencontainers.image.description="Runtime control, operator, effect proxy, and Certificate checker" \
      org.opencontainers.image.source="https://github.com/eunomia-bpf/agent-check-restore-safety" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.base.name="${RUNTIME_IMAGE}"

RUN apk add --no-cache ca-certificates && \
    addgroup -S -g 65532 safechange && \
    adduser -S -D -H -u 65532 -G safechange safechange
COPY --from=build --chmod=0555 \
    /out/control \
    /out/safe-change \
    /out/effect-proxy \
    /out/check-certificate \
    /usr/local/bin/

USER 65532:65532
CMD ["safe-change"]
