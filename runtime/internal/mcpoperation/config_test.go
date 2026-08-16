package mcpoperation

import (
	"fmt"
	"strings"
	"testing"
)

const validConfigJSON = `{
  "schema": 1,
  "tools": [{
    "name": "charge_payment",
    "description": "Commit one payment through the continuity runtime.",
    "kind": "protected_commit",
    "arguments": [
      {"name":"effect_id","description":"Stable business effect.","type":"string","required":true,"max_length":128},
      {"name":"priority","type":"integer","required":false},
      {"name":"notify","type":"boolean","required":false},
      {"name":"currency","type":"string","required":true,"max_length":3,"enum":["USD","EUR"]}
    ]
  }]
}`

func TestParseConfigAcceptsStrictBoundedTools(t *testing.T) {
	config, err := ParseConfig([]byte(validConfigJSON))
	if err != nil {
		t.Fatal(err)
	}
	if config.Schema != ConfigSchema || len(config.Tools) != 1 || config.Tools[0].Kind != "protected_commit" || len(config.Tools[0].Arguments) != 4 {
		t.Fatalf("config = %+v", config)
	}
	config.Tools[0].Arguments[0].Enum = append(config.Tools[0].Arguments[0].Enum, "mutated")
	reparsed, err := ParseConfig([]byte(validConfigJSON))
	if err != nil || len(reparsed.Tools[0].Arguments[0].Enum) != 0 {
		t.Fatalf("ParseConfig retained caller mutation: %+v error=%v", reparsed, err)
	}
}

func TestParseConfigRejectsAuthorityAndSchemaMutations(t *testing.T) {
	tests := map[string]string{
		"unknown field":       strings.Replace(validConfigJSON, `"schema": 1`, `"schema": 1, "url": "https://provider"`, 1),
		"duplicate field":     strings.Replace(validConfigJSON, `"schema": 1`, `"schema": 1, "schema": 1`, 1),
		"wrong schema":        strings.Replace(validConfigJSON, `"schema": 1`, `"schema": 2`, 1),
		"multiple values":     validConfigJSON + `{}`,
		"no tools":            `{"schema":1,"tools":[]}`,
		"slash name":          strings.Replace(validConfigJSON, `"charge_payment"`, `"charge/payment"`, 1),
		"duplicate tool":      `{"schema":1,"tools":[{"name":"same","description":"first","kind":"one","arguments":[]},{"name":"same","description":"second","kind":"two","arguments":[]}]}`,
		"empty description":   strings.Replace(validConfigJSON, `"Commit one payment through the continuity runtime."`, ``, 1),
		"empty kind":          strings.Replace(validConfigJSON, `"protected_commit"`, ``, 1),
		"duplicate argument":  strings.Replace(validConfigJSON, `{"name":"priority"`, `{"name":"effect_id"`, 1),
		"unsupported type":    strings.Replace(validConfigJSON, `"type":"integer"`, `"type":"object"`, 1),
		"unbounded string":    strings.Replace(validConfigJSON, `,"max_length":128`, ``, 1),
		"string bound on int": strings.Replace(validConfigJSON, `"type":"integer","required":false`, `"type":"integer","required":false,"max_length":3`, 1),
		"duplicate enum":      strings.Replace(validConfigJSON, `["USD","EUR"]`, `["USD","USD"]`, 1),
		"long enum":           strings.Replace(validConfigJSON, `["USD","EUR"]`, `["TOOLONG"]`, 1),
	}
	for name, input := range tests {
		t.Run(name, func(t *testing.T) {
			if config, err := ParseConfig([]byte(input)); err == nil {
				t.Fatalf("mutation accepted: %+v", config)
			}
		})
	}
}

func TestParseConfigBoundsDocumentAndToolCount(t *testing.T) {
	if _, err := ParseConfig([]byte(strings.Repeat(" ", MaxConfigBytes+1))); err == nil {
		t.Fatal("oversized config accepted")
	}
	tools := make([]string, MaxTools+1)
	for index := range tools {
		tools[index] = fmt.Sprintf(`{"name":"tool%d","description":"tool","kind":"kind","arguments":[]}`, index)
	}
	if _, err := ParseConfig([]byte(`{"schema":1,"tools":[` + strings.Join(tools, ",") + `]}`)); err == nil {
		t.Fatal("too many tools accepted")
	}
}
