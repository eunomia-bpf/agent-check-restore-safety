FROM golang:1.22.2-alpine3.19 AS build

WORKDIR /src
COPY go.mod ./
COPY . ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/control ./cmd/control && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/order ./cmd/order && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/payment ./cmd/payment && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/ingress ./cmd/ingress

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=build /out/control /out/order /out/payment /out/ingress /usr/local/bin/
