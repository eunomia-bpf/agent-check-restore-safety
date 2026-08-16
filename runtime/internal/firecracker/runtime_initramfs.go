package firecracker

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

const maxRuntimeConfigBytes = 1 << 20

// BuildRuntimeInitramfs writes a deterministic, uncompressed newc archive for
// a general runtime guest. The init program is subject to the same static-ELF
// and 64 MiB limits as BuildInitramfs. configJSON is retained byte-for-byte and
// is deliberately treated only as one bounded JSON object; business fields are
// interpreted by the guest runtime, not by this archive builder.
func BuildRuntimeInitramfs(writer io.Writer, initBinary, configJSON []byte) error {
	if writer == nil {
		return errors.New("runtime initramfs writer is nil")
	}
	if len(initBinary) == 0 || len(initBinary) > maxInitBytes {
		return fmt.Errorf("runtime init binary must contain 1 byte to %d bytes", maxInitBytes)
	}
	if len(configJSON) == 0 || len(configJSON) > maxRuntimeConfigBytes {
		return fmt.Errorf("config.json must contain 1 byte to %d bytes", maxRuntimeConfigBytes)
	}
	if err := validateStaticELF(initBinary); err != nil {
		return err
	}
	if err := validateRuntimeConfigJSON(configJSON); err != nil {
		return err
	}

	entries := []archiveEntry{
		{name: "dev", mode: modeDirectory | 0o755, directory: true},
		{name: "dev/console", mode: modeCharacter | 0o600, rdevMajor: 5, rdevMinor: 1},
		{name: "init", mode: modeRegular | 0o555, data: initBinary},
		{name: "proc", mode: modeDirectory | 0o555, directory: true},
		{name: "sys", mode: modeDirectory | 0o555, directory: true},
		{name: "run", mode: modeDirectory | 0o755, directory: true},
		{name: "tmp", mode: modeDirectory | 0o1777, directory: true},
		{name: "opt", mode: modeDirectory | 0o555, directory: true},
		{name: "workspace", mode: modeDirectory | 0o755, directory: true},
		{name: "home", mode: modeDirectory | 0o755, directory: true},
		{name: "config.json", mode: modeRegular | 0o400, data: configJSON},
	}

	counting := &countingWriter{writer: writer}
	for index, entry := range entries {
		if err := writeNewcEntry(counting, uint32(index+1), entry); err != nil {
			return err
		}
	}
	if err := writeNewcEntry(counting, uint32(len(entries)+1), archiveEntry{name: "TRAILER!!!"}); err != nil {
		return err
	}
	return writePadding(counting, archiveBlock)
}

func validateRuntimeConfigJSON(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	first, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("decode config.json: %w", err)
	}
	if delimiter, ok := first.(json.Delim); !ok || delimiter != '{' {
		return errors.New("config.json must be one JSON object")
	}
	for decoder.More() {
		field, err := decoder.Token()
		if err != nil {
			return fmt.Errorf("decode config.json field: %w", err)
		}
		if _, ok := field.(string); !ok {
			return errors.New("config.json has a non-string field name")
		}
		var value json.RawMessage
		if err := decoder.Decode(&value); err != nil {
			return fmt.Errorf("decode config.json value: %w", err)
		}
	}
	last, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("close config.json object: %w", err)
	}
	if delimiter, ok := last.(json.Delim); !ok || delimiter != '}' {
		return errors.New("config.json object is not closed")
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return fmt.Errorf("config.json has trailing value %v", token)
		}
		return fmt.Errorf("config.json has trailing data: %w", err)
	}
	return nil
}
