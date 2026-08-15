package effectproxy

import (
	"fmt"
	"strings"
	"testing"
)

const validConfig = `{
  "schema": 1,
  "routes": [{
    "name": "charge-payment",
    "kind": "charge-payment",
    "method": "POST",
    "url": "http://payment.internal/v1/charge",
    "content_types": ["application/json; charset=utf-8", "application/octet-stream"]
  }]
}`

func TestParseConfigCanonicalizesStrictConfig(t *testing.T) {
	config, err := ParseConfig([]byte(validConfig))
	if err != nil {
		t.Fatal(err)
	}
	if config.Schema != ConfigSchema || len(config.Routes) != 1 {
		t.Fatalf("config = %+v", config)
	}
	route := config.Routes[0]
	if route.Name != "charge-payment" || route.Kind != "charge-payment" || route.Method != "POST" ||
		route.URL != "http://payment.internal/v1/charge" {
		t.Fatalf("route = %+v", route)
	}
	if got := strings.Join(route.ContentTypes, ","); got != "application/json; charset=utf-8,application/octet-stream" {
		t.Fatalf("Content-Types = %q", got)
	}
}

func TestParseConfigRejectsSchemaAndAuthorityMutations(t *testing.T) {
	tests := map[string]string{
		"unknown-field":     strings.Replace(validConfig, `"schema": 1`, `"schema": 1, "extra": true`, 1),
		"duplicate-field":   strings.Replace(validConfig, `"schema": 1`, `"schema": 1, "schema": 1`, 1),
		"wrong-schema":      strings.Replace(validConfig, `"schema": 1`, `"schema": 2`, 1),
		"multiple-values":   validConfig + `{}`,
		"missing-routes":    `{"schema":1,"routes":[]}`,
		"duplicate-name":    `{"schema":1,"routes":[{"name":"same","kind":"one","method":"POST","url":"https://fixed/one","content_types":["application/json"]},{"name":"same","kind":"two","method":"POST","url":"https://fixed/two","content_types":["application/json"]}]}`,
		"slash-name":        strings.Replace(validConfig, `"charge-payment"`, `"charge/payment"`, 1),
		"leading-dash-name": strings.Replace(validConfig, `"charge-payment"`, `"-charge"`, 1),
		"empty-kind":        strings.Replace(validConfig, `"kind": "charge-payment"`, `"kind": ""`, 1),
		"lowercase-method":  strings.Replace(validConfig, `"method": "POST"`, `"method": "post"`, 1),
		"connect-method":    strings.Replace(validConfig, `"method": "POST"`, `"method": "CONNECT"`, 1),
		"relative-url":      strings.Replace(validConfig, `http://payment.internal/v1/charge`, `/v1/charge`, 1),
		"file-url":          strings.Replace(validConfig, `http://payment.internal/v1/charge`, `file:///tmp/effect`, 1),
		"userinfo-url":      strings.Replace(validConfig, `http://payment.internal/v1/charge`, `http://secret@payment.internal/v1/charge`, 1),
		"fragment-url":      strings.Replace(validConfig, `http://payment.internal/v1/charge`, `http://payment.internal/v1/charge#other`, 1),
		"missing-types":     strings.Replace(validConfig, `["application/json; charset=utf-8", "application/octet-stream"]`, `[]`, 1),
		"duplicate-types":   strings.Replace(validConfig, `["application/json; charset=utf-8", "application/octet-stream"]`, `["APPLICATION/JSON; charset=utf-8", "application/json;charset=utf-8"]`, 1),
		"invalid-type":      strings.Replace(validConfig, `application/octet-stream`, `not a media type`, 1),
	}
	for name, input := range tests {
		t.Run(name, func(t *testing.T) {
			if config, err := ParseConfig([]byte(input)); err == nil {
				t.Fatalf("mutation accepted: %+v", config)
			}
		})
	}
}

func TestParseConfigBoundsInput(t *testing.T) {
	input := []byte(strings.Repeat(" ", MaxConfigBytes+1))
	if _, err := ParseConfig(input); err == nil {
		t.Fatal("oversized config accepted")
	}
	routes := make([]string, MaxRoutes+1)
	for index := range routes {
		routes[index] = fmt.Sprintf(`{"name":"r%d","kind":"kind","method":"POST","url":"http://fixed/%d","content_types":["application/json"]}`, index, index)
	}
	input = []byte(fmt.Sprintf(`{"schema":1,"routes":[%s]}`, strings.Join(routes, ",")))
	if _, err := ParseConfig(input); err == nil {
		t.Fatal("too many routes accepted")
	}
}
