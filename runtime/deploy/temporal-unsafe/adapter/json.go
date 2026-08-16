package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

// rejectDuplicateJSONNames walks every object in one JSON value. The standard
// library otherwise accepts a later duplicate member and silently changes the
// meaning of an operator configuration or provider record.
func rejectDuplicateJSONNames(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var consumeValue func() error
	consumeValue = func() error {
		token, err := decoder.Token()
		if err != nil {
			return err
		}
		delimiter, ok := token.(json.Delim)
		if !ok {
			return nil
		}
		switch delimiter {
		case '{':
			seen := make(map[string]bool)
			for decoder.More() {
				nameToken, err := decoder.Token()
				if err != nil {
					return err
				}
				name, ok := nameToken.(string)
				if !ok {
					return errors.New("object member name is not a string")
				}
				if seen[name] {
					return fmt.Errorf("duplicate JSON field %q", name)
				}
				seen[name] = true
				if err := consumeValue(); err != nil {
					return err
				}
			}
			closing, err := decoder.Token()
			if err != nil {
				return err
			}
			if closing != json.Delim('}') {
				return errors.New("object is not closed")
			}
		case '[':
			for decoder.More() {
				if err := consumeValue(); err != nil {
					return err
				}
			}
			closing, err := decoder.Token()
			if err != nil {
				return err
			}
			if closing != json.Delim(']') {
				return errors.New("array is not closed")
			}
		default:
			return errors.New("unexpected closing delimiter")
		}
		return nil
	}
	return consumeValue()
}

func decodeExactObject(
	data []byte,
	label string,
	required map[string]bool,
	optional map[string]bool,
) (map[string]json.RawMessage, error) {
	if err := rejectDuplicateJSONNames(data); err != nil {
		return nil, fmt.Errorf("decode %s: %w", label, err)
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return nil, fmt.Errorf("%s is not a JSON object", label)
	}
	allowed := make(map[string]bool, len(required)+len(optional))
	for name := range required {
		allowed[name] = true
	}
	for name := range optional {
		allowed[name] = true
	}
	fields := make(map[string]json.RawMessage, len(allowed))
	for decoder.More() {
		nameToken, err := decoder.Token()
		if err != nil {
			return nil, fmt.Errorf("decode %s member: %w", label, err)
		}
		name, ok := nameToken.(string)
		if !ok {
			return nil, fmt.Errorf("%s member name is not a string", label)
		}
		if !allowed[name] {
			return nil, fmt.Errorf("%s contains unknown field %q", label, name)
		}
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return nil, fmt.Errorf("decode %s field %q: %w", label, name, err)
		}
		fields[name] = raw
	}
	end, err := decoder.Token()
	if err != nil || end != json.Delim('}') {
		return nil, fmt.Errorf("%s has an invalid terminator", label)
	}
	for name := range required {
		if _, ok := fields[name]; !ok {
			return nil, fmt.Errorf("%s is missing field %q", label, name)
		}
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, fmt.Errorf("%s contains multiple JSON values", label)
		}
		return nil, fmt.Errorf("decode %s end: %w", label, err)
	}
	return fields, nil
}

func decodeNonNullField(fields map[string]json.RawMessage, name string, target any) error {
	raw, ok := fields[name]
	if !ok {
		return fmt.Errorf("missing field %q", name)
	}
	if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
		return fmt.Errorf("field %q is null", name)
	}
	if err := json.Unmarshal(raw, target); err != nil {
		return fmt.Errorf("decode field %q: %w", name, err)
	}
	return nil
}
