FROM golang:1.22.2-alpine3.19 AS build

WORKDIR /src
COPY go.mod ./
COPY . ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/control ./cmd/control && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/safe-change ./cmd/safe-change && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/effect-proxy ./cmd/effect-proxy && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/order ./cmd/order && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/payment ./cmd/payment && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/ingress ./cmd/ingress && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/deathstar-adapter ./cmd/deathstar-adapter

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=build /out/control /out/safe-change /out/effect-proxy /out/order /out/payment /out/ingress /out/deathstar-adapter /usr/local/bin/
