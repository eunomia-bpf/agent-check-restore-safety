package provideradapter

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestSingleAttemptRequestOwnsANonRewindableBody(t *testing.T) {
	body := []byte("provider-work")
	request, err := NewSingleAttemptRequest(
		context.Background(), http.MethodPost, "https://provider.example/v1/work?mode=live", body,
	)
	if err != nil {
		t.Fatal(err)
	}
	body[0] = 'X'
	encoded, err := io.ReadAll(request.Body)
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != "provider-work" || request.ContentLength != int64(len(encoded)) {
		t.Fatalf("owned body = %q, ContentLength = %d", encoded, request.ContentLength)
	}
	if request.GetBody != nil {
		t.Fatal("single-attempt request exposes a rewind function")
	}

	for _, test := range []struct {
		name   string
		ctx    context.Context
		target string
	}{
		{name: "nil-context", target: "https://provider.example", ctx: nil},
		{name: "relative", target: "/provider", ctx: context.Background()},
		{name: "credentials", target: "https://token@provider.example/v1", ctx: context.Background()},
		{name: "fragment", target: "https://provider.example/v1#secret", ctx: context.Background()},
		{name: "wrong-scheme", target: "file:///provider", ctx: context.Background()},
	} {
		t.Run(test.name, func(t *testing.T) {
			if _, err := NewSingleAttemptRequest(test.ctx, http.MethodPost, test.target, nil); err == nil {
				t.Fatalf("invalid target %q was accepted", test.target)
			}
		})
	}
}

func TestHTTPClientDoesNotFollowRedirects(t *testing.T) {
	var redirected atomic.Int32
	destination := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		redirected.Add(1)
	}))
	defer destination.Close()
	source := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		http.Redirect(writer, &http.Request{}, destination.URL, http.StatusTemporaryRedirect)
	}))
	defer source.Close()

	client, err := NewHTTPClient(nil, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	request, err := NewSingleAttemptRequest(context.Background(), http.MethodPost, source.URL, []byte("effect"))
	if err != nil {
		t.Fatal(err)
	}
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusTemporaryRedirect || redirected.Load() != 0 {
		t.Fatalf("redirect response = %d, followed = %d", response.StatusCode, redirected.Load())
	}
	if _, err := NewHTTPClient(nil, 0); err == nil {
		t.Fatal("zero provider timeout was accepted")
	}
}

func TestDefaultHTTPClientIgnoresAmbientProxy(t *testing.T) {
	t.Setenv("HTTP_PROXY", "http://ambient-proxy.invalid:3128")
	t.Setenv("HTTPS_PROXY", "http://ambient-proxy.invalid:3128")
	client, err := NewHTTPClient(nil, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	transport, ok := client.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("default transport type = %T", client.Transport)
	}
	if transport == http.DefaultTransport {
		t.Fatal("NewHTTPClient reused the process-global default transport")
	}
	if transport.Proxy != nil {
		t.Fatal("default provider client can consult ambient proxy settings")
	}
}

func TestHTTPTransportCannotReplaySingleAttemptProviderRequest(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	var deliveries atomic.Int32
	serverDone := make(chan error, 1)
	go func() {
		connection, err := listener.Accept()
		if err != nil {
			serverDone <- err
			return
		}
		reader := bufio.NewReader(connection)
		first, err := http.ReadRequest(reader)
		if err != nil {
			_ = connection.Close()
			serverDone <- err
			return
		}
		_, _ = io.Copy(io.Discard, first.Body)
		_ = first.Body.Close()
		deliveries.Add(1)
		if _, err := fmt.Fprint(connection, "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok"); err != nil {
			_ = connection.Close()
			serverDone <- err
			return
		}

		second, err := http.ReadRequest(reader)
		if err != nil {
			_ = connection.Close()
			serverDone <- err
			return
		}
		_, _ = io.Copy(io.Discard, second.Body)
		_ = second.Body.Close()
		deliveries.Add(1)
		// The provider accepted the second delivery, then the reused connection
		// disappeared before a response reached the client.
		_ = connection.Close()

		tcpListener := listener.(*net.TCPListener)
		if err := tcpListener.SetDeadline(time.Now().Add(750 * time.Millisecond)); err != nil {
			serverDone <- err
			return
		}
		retryConnection, err := listener.Accept()
		if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
			serverDone <- nil
			return
		}
		if err != nil {
			serverDone <- err
			return
		}
		defer retryConnection.Close()
		retried, err := http.ReadRequest(bufio.NewReader(retryConnection))
		if err != nil {
			serverDone <- err
			return
		}
		_, _ = io.Copy(io.Discard, retried.Body)
		_ = retried.Body.Close()
		deliveries.Add(1)
		serverDone <- errors.New("net/http implicitly replayed one provider request")
	}()

	transport := &http.Transport{}
	defer transport.CloseIdleConnections()
	client, err := NewHTTPClient(transport, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	target := "http://" + listener.Addr().String() + "/effect"
	first, err := NewSingleAttemptRequest(context.Background(), http.MethodPost, target, []byte(`{"warm":true}`))
	if err != nil {
		t.Fatal(err)
	}
	first.Header.Set(HeaderIdempotencyKey, "warm-operation")
	response, err := client.Do(first)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.Copy(io.Discard, response.Body)
	if err := response.Body.Close(); err != nil {
		t.Fatal(err)
	}

	second, err := NewSingleAttemptRequest(context.Background(), http.MethodPost, target, []byte(`{"commit":true}`))
	if err != nil {
		t.Fatal(err)
	}
	second.Header.Set(HeaderIdempotencyKey, "lost-response-operation")
	if response, err := client.Do(second); err == nil {
		_ = response.Body.Close()
		t.Fatal("lost provider response unexpectedly succeeded")
	}
	if err := <-serverDone; err != nil {
		t.Fatal(err)
	}
	if got := deliveries.Load(); got != 2 {
		t.Fatalf("provider deliveries = %d, want 2", got)
	}
}

func TestSingleAttemptRequestRejectsInvalidMethod(t *testing.T) {
	if _, err := NewSingleAttemptRequest(context.Background(), "", "https://provider.example", nil); err == nil ||
		!strings.Contains(err.Error(), "method is empty") {
		t.Fatalf("empty method error = %v", err)
	}
	if _, err := NewSingleAttemptRequest(context.Background(), "BAD METHOD", "https://provider.example", nil); err == nil ||
		!strings.Contains(err.Error(), "invalid method") {
		t.Fatalf("invalid method error = %v", err)
	}
}
