FROM docker.io/library/golang:1.25.13-alpine@sha256:844b27705f54e73773e0f9bc3c780633b9d7f4b4831bf35cdad02a81a4c80bd0 AS build

WORKDIR /src
COPY go.mod go.sum ./
COPY . ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/control ./cmd/control && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/safe-change ./cmd/safe-change && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/effect-proxy ./cmd/effect-proxy && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/order ./cmd/order && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/payment ./cmd/payment && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/ingress ./cmd/ingress && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/deathstar-adapter ./cmd/deathstar-adapter

FROM docker.io/library/alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412
ARG SOURCE_REVISION=unknown
ARG SOURCE_TREE_SHA256=unknown
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      io.safe-change.source-tree.sha256="${SOURCE_TREE_SHA256}"
RUN apk add --no-cache ca-certificates
COPY --from=build /out/control /out/safe-change /out/effect-proxy /out/order /out/payment /out/ingress /out/deathstar-adapter /usr/local/bin/
