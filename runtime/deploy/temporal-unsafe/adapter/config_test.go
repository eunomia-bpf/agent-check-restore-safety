package main

import (
	"fmt"
	"strings"
	"testing"
)

const validAdapterConfig = `{
  "schema": 1,
  "routes": [
    {
      "path": "/v1/charge",
      "closure_version": {"mode": "absent"},
      "kind": "charge-v1",
      "target": "http://payment:8081/v1/charge",
      "call_id_mode": "order_id"
    },
    {
      "path": "/v2/charge",
      "closure_version": {"mode": "absent"},
      "kind": "charge-v2",
      "target": "http://payment:8081/v2/charge",
      "call_id_mode": "order_id"
    },
    {
      "path": "/v1/complete",
      "closure_version": {"mode": "absent"},
      "kind": "finish-v1",
      "target": "http://completion:8081/v1/complete",
      "call_id_mode": "complete_order_id"
    },
    {
      "path": "/v1/complete",
      "closure_version": {"mode": "exact", "value": "unsafe-v2"},
      "kind": "finish-v2",
      "target": "http://completion:8081/v1/complete",
      "call_id_mode": "complete_order_id"
    }
  ]
}`

func TestParseConfigBindsEveryAuthorityDimension(t *testing.T) {
	config, err := ParseConfig([]byte(validAdapterConfig))
	if err != nil {
		t.Fatal(err)
	}
	if config.Schema != configSchema || len(config.Routes) != 4 {
		t.Fatalf("config = %+v", config)
	}
	target := config.Routes[3]
	if target.Path != "/v1/complete" || target.ClosureVersion.Mode != closureExact ||
		target.ClosureVersion.Value != "unsafe-v2" || target.Kind != "finish-v2" ||
		target.Target != "http://completion:8081/v1/complete" || target.CallIDMode != callIDCompleteOrder {
		t.Fatalf("target route = %+v", target)
	}
}

func TestParseConfigRejectsAuthorityMutations(t *testing.T) {
	tests := map[string]string{
		"unknown top field":          strings.Replace(validAdapterConfig, `"schema": 1`, `"schema": 1, "extra": true`, 1),
		"duplicate top field":        strings.Replace(validAdapterConfig, `"schema": 1`, `"schema": 1, "schema": 1`, 1),
		"unknown route field":        strings.Replace(validAdapterConfig, `"kind": "charge-v1"`, `"kind": "charge-v1", "method": "POST"`, 1),
		"wrong schema":               strings.Replace(validAdapterConfig, `"schema": 1`, `"schema": 2`, 1),
		"multiple values":            validAdapterConfig + `{}`,
		"arbitrary path":             strings.Replace(validAdapterConfig, `"/v1/charge"`, `"/proxy"`, 1),
		"target path mismatch":       strings.Replace(validAdapterConfig, `http://payment:8081/v1/charge`, `http://payment:8081/v1/query`, 1),
		"target query":               strings.Replace(validAdapterConfig, `http://payment:8081/v1/charge`, `http://payment:8081/v1/charge?next=http://other`, 1),
		"target credentials":         strings.Replace(validAdapterConfig, `http://payment:8081/v1/charge`, `http://secret@payment:8081/v1/charge`, 1),
		"relative target":            strings.Replace(validAdapterConfig, `http://payment:8081/v1/charge`, `/v1/charge`, 1),
		"empty kind":                 strings.Replace(validAdapterConfig, `"kind": "charge-v1"`, `"kind": ""`, 1),
		"charge completion identity": strings.Replace(validAdapterConfig, `"call_id_mode": "order_id"`, `"call_id_mode": "complete_order_id"`, 1),
		"completion order identity":  strings.Replace(validAdapterConfig, `"call_id_mode": "complete_order_id"`, `"call_id_mode": "order_id"`, 1),
		"unknown call mode":          strings.Replace(validAdapterConfig, `"call_id_mode": "order_id"`, `"call_id_mode": "header"`, 1),
		"unknown closure mode":       strings.Replace(validAdapterConfig, `"mode": "absent"`, `"mode": "any"`, 1),
		"absent with value":          strings.Replace(validAdapterConfig, `{"mode": "absent"}`, `{"mode": "absent", "value": "v1"}`, 1),
		"exact without value":        strings.Replace(validAdapterConfig, `{"mode": "exact", "value": "unsafe-v2"}`, `{"mode": "exact"}`, 1),
		"ambiguous binding":          strings.Replace(validAdapterConfig, `"path": "/v2/charge"`, `"path": "/v1/charge"`, 1),
	}
	for name, input := range tests {
		t.Run(name, func(t *testing.T) {
			if config, err := ParseConfig([]byte(input)); err == nil {
				t.Fatalf("mutation accepted: %+v", config)
			}
		})
	}
}

func TestParseConfigBoundsInputAndBindings(t *testing.T) {
	if _, err := ParseConfig([]byte(strings.Repeat(" ", maxConfigBytes+1))); err == nil {
		t.Fatal("oversized config accepted")
	}
	routes := make([]string, maxRoutes+1)
	for index := range routes {
		routes[index] = fmt.Sprintf(
			`{"path":"/v1/complete","closure_version":{"mode":"exact","value":"v%d"},"kind":"finish","target":"http://completion/v1/complete","call_id_mode":"complete_order_id"}`,
			index,
		)
	}
	input := fmt.Sprintf(`{"schema":1,"routes":[%s]}`, strings.Join(routes, ","))
	if _, err := ParseConfig([]byte(input)); err == nil {
		t.Fatal("too many bindings accepted")
	}
}
