package provideradapter

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/url"
	"time"
)

// singleAttemptReader intentionally does not expose bytes.Reader's rewind
// methods. net/http may otherwise replay a request carrying an
// Idempotency-Key after a reused-connection failure without returning control
// to the adapter.
type singleAttemptReader struct {
	reader *bytes.Reader
}

func (reader *singleAttemptReader) Read(destination []byte) (int, error) {
	return reader.reader.Read(destination)
}

// NewSingleAttemptRequest constructs an HTTP request whose body cannot be
// rewound by net/http. The body is copied so later caller mutation cannot
// change the provider request.
func NewSingleAttemptRequest(ctx context.Context, method, target string, body []byte) (*http.Request, error) {
	if ctx == nil {
		return nil, errors.New("provider request context is nil")
	}
	if method == "" {
		return nil, errors.New("provider request method is empty")
	}
	parsed, err := url.Parse(target)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return nil, errors.New("provider target must be an absolute HTTP(S) URL")
	}
	if parsed.User != nil || parsed.Fragment != "" {
		return nil, errors.New("provider target cannot contain credentials or a fragment")
	}
	ownedBody := append([]byte(nil), body...)
	request, err := http.NewRequestWithContext(ctx, method, parsed.String(), &singleAttemptReader{
		reader: bytes.NewReader(ownedBody),
	})
	if err != nil {
		return nil, err
	}
	request.ContentLength = int64(len(ownedBody))
	request.GetBody = nil
	return request, nil
}

// NewHTTPClient returns a client that never follows redirects. A nil transport
// clones the default Transport but disables its ambient proxy lookup. A
// non-nil transport is used unchanged, so its proxy policy remains the
// caller's responsibility. To prevent implicit request replay, use this client
// with requests constructed by NewSingleAttemptRequest.
func NewHTTPClient(transport http.RoundTripper, timeout time.Duration) (*http.Client, error) {
	if timeout <= 0 {
		return nil, errors.New("provider HTTP timeout must be positive")
	}
	if transport == nil {
		defaultTransport, ok := http.DefaultTransport.(*http.Transport)
		if !ok {
			return nil, errors.New("default HTTP transport has an unsupported type")
		}
		directTransport := defaultTransport.Clone()
		// A provider credential is added after the durable runtime boundary.
		// Never hand that request to an ambient HTTP_PROXY selected outside the
		// adapter's explicit configuration.
		directTransport.Proxy = nil
		transport = directTransport
	}
	return &http.Client{
		Transport: transport,
		Timeout:   timeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}, nil
}
