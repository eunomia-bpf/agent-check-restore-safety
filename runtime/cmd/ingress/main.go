// Command ingress exposes only two fixed HTTP routes into an otherwise
// internal container network. It is not a general forward proxy.
package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	var controlListen, orderListen, controlUpstream, orderUpstream string
	flag.StringVar(&controlListen, "control-listen", "0.0.0.0:8787", "control ingress listen address")
	flag.StringVar(&orderListen, "order-listen", "0.0.0.0:8080", "order ingress listen address")
	flag.StringVar(&controlUpstream, "control-upstream", "http://control:8787", "fixed control upstream")
	flag.StringVar(&orderUpstream, "order-upstream", "http://order:8080", "fixed order upstream")
	flag.Parse()

	controlTarget := mustHTTPURL(controlUpstream)
	orderTarget := mustHTTPURL(orderUpstream)
	controlListener, err := net.Listen("tcp", controlListen)
	if err != nil {
		log.Fatal(err)
	}
	orderListener, err := net.Listen("tcp", orderListen)
	if err != nil {
		controlListener.Close()
		log.Fatal(err)
	}
	controlServer := serverFor(controlTarget)
	orderServer := serverFor(orderTarget)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = controlServer.Shutdown(shutdown)
		_ = orderServer.Shutdown(shutdown)
	}()
	errorsChannel := make(chan error, 2)
	go func() { errorsChannel <- controlServer.Serve(controlListener) }()
	go func() { errorsChannel <- orderServer.Serve(orderListener) }()
	log.Printf("fixed ingress listening on control=%s order=%s", controlListen, orderListen)
	if err := <-errorsChannel; err != nil && !errors.Is(err, http.ErrServerClosed) {
		stop()
		log.Fatal(err)
	}
}

func mustHTTPURL(value string) *url.URL {
	target, err := url.Parse(value)
	if err != nil || (target.Scheme != "http" && target.Scheme != "https") || target.Host == "" || target.User != nil || target.Fragment != "" {
		log.Fatalf("invalid fixed upstream %q", value)
	}
	return target
}

func serverFor(target *url.URL) *http.Server {
	proxy := &httputil.ReverseProxy{
		Rewrite: func(request *httputil.ProxyRequest) {
			request.SetURL(target)
			request.SetXForwarded()
		},
		Transport: &http.Transport{
			Proxy:                 http.ProxyFromEnvironment,
			DialContext:           (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
			ResponseHeaderTimeout: 40 * time.Second,
		},
		ErrorHandler: func(writer http.ResponseWriter, _ *http.Request, _ error) {
			http.Error(writer, "fixed upstream unavailable", http.StatusBadGateway)
		},
	}
	return &http.Server{
		Handler: proxy, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second,
	}
}
