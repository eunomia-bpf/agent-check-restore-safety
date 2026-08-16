// Package firecracker contains host-side helpers for constructing the minimal
// Firecracker execution boundary. It deliberately does not create or attach a
// root disk: the guest is a static PID 1 plus one immutable request in initramfs.
package firecracker

import (
	"bytes"
	"debug/elf"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

const (
	newcMagic       = "070701"
	newcHeaderBytes = 110
	archiveBlock    = 512
	maxInitBytes    = 64 << 20
	maxRequestBytes = 1 << 20

	modeDirectory = uint32(0040000)
	modeRegular   = uint32(0100000)
	modeCharacter = uint32(0020000)
)

type archiveEntry struct {
	name      string
	mode      uint32
	data      []byte
	rdevMajor uint32
	rdevMinor uint32
	directory bool
}

// BuildInitramfs writes a deterministic, uncompressed "newc" initramfs.
// initBinary must be a static Linux ELF with no PT_INTERP segment. requestJSON
// must contain exactly call_id, kind, and body. Every owner, timestamp, inode,
// path, mode, and padding byte is fixed, so identical inputs produce identical
// archive bytes on every host.
func BuildInitramfs(writer io.Writer, initBinary, requestJSON []byte) error {
	if writer == nil {
		return errors.New("initramfs writer is nil")
	}
	if len(initBinary) == 0 || len(initBinary) > maxInitBytes {
		return fmt.Errorf("init binary must contain 1 byte to %d bytes", maxInitBytes)
	}
	if len(requestJSON) == 0 || len(requestJSON) > maxRequestBytes {
		return fmt.Errorf("request.json must contain 1 byte to %d bytes", maxRequestBytes)
	}
	if err := validateStaticELF(initBinary); err != nil {
		return err
	}
	if err := validateThreeFieldRequest(requestJSON); err != nil {
		return err
	}

	entries := []archiveEntry{
		{name: "dev", mode: modeDirectory | 0o755, directory: true},
		{name: "dev/console", mode: modeCharacter | 0o600, rdevMajor: 5, rdevMinor: 1},
		{name: "init", mode: modeRegular | 0o555, data: initBinary},
		{name: "proc", mode: modeDirectory | 0o555, directory: true},
		{name: "request.json", mode: modeRegular | 0o444, data: requestJSON},
		{name: "run", mode: modeDirectory | 0o755, directory: true},
		{name: "sys", mode: modeDirectory | 0o555, directory: true},
		{name: "tmp", mode: modeDirectory | 0o1777, directory: true},
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

func validateStaticELF(data []byte) error {
	executable, err := elf.NewFile(bytes.NewReader(data))
	if err != nil {
		return fmt.Errorf("init binary is not ELF: %w", err)
	}
	defer executable.Close()
	if executable.Type != elf.ET_EXEC && executable.Type != elf.ET_DYN {
		return fmt.Errorf("init ELF has unsupported type %s", executable.Type)
	}
	if executable.Machine != elf.EM_X86_64 && executable.Machine != elf.EM_AARCH64 {
		return fmt.Errorf("init ELF has unsupported machine %s", executable.Machine)
	}
	for _, program := range executable.Progs {
		if program.Type == elf.PT_INTERP {
			return errors.New("init ELF is dynamically linked; build firecracker-guest with CGO_ENABLED=0")
		}
	}
	return nil
}

func validateThreeFieldRequest(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	first, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("decode request.json: %w", err)
	}
	if delimiter, ok := first.(json.Delim); !ok || delimiter != '{' {
		return errors.New("request.json must be one JSON object")
	}
	seen := make(map[string]bool, 3)
	for decoder.More() {
		fieldToken, err := decoder.Token()
		if err != nil {
			return fmt.Errorf("decode request.json field: %w", err)
		}
		field, ok := fieldToken.(string)
		if !ok {
			return errors.New("request.json has a non-string field name")
		}
		if field != "call_id" && field != "kind" && field != "body" {
			return fmt.Errorf("request.json contains forbidden field %q", field)
		}
		if seen[field] {
			return fmt.Errorf("request.json repeats field %q", field)
		}
		seen[field] = true
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return fmt.Errorf("decode request.json field %q: %w", field, err)
		}
		switch field {
		case "call_id", "kind":
			var value string
			if err := json.Unmarshal(raw, &value); err != nil || value == "" {
				return fmt.Errorf("request.json field %q must be a non-empty string", field)
			}
		case "body":
			var value []byte
			if err := json.Unmarshal(raw, &value); err != nil || value == nil {
				return errors.New("request.json body must be a base64 string")
			}
		}
	}
	last, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("close request.json object: %w", err)
	}
	if delimiter, ok := last.(json.Delim); !ok || delimiter != '}' {
		return errors.New("request.json object is not closed")
	}
	if len(seen) != 3 || !seen["call_id"] || !seen["kind"] || !seen["body"] {
		return errors.New("request.json must contain exactly call_id, kind, and body")
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return fmt.Errorf("request.json has trailing value %v", token)
		}
		return fmt.Errorf("request.json has trailing data: %w", err)
	}
	return nil
}

func writeNewcEntry(writer *countingWriter, inode uint32, entry archiveEntry) error {
	if entry.name == "" || bytes.IndexByte([]byte(entry.name), 0) >= 0 {
		return errors.New("newc entry has an invalid name")
	}
	if uint64(len(entry.data)) > uint64(^uint32(0)) || len(entry.name)+1 > int(^uint32(0)) {
		return errors.New("newc entry exceeds 32-bit size fields")
	}
	nlink := uint32(1)
	if entry.directory {
		nlink = 2
	}
	header := fmt.Sprintf(
		"%s%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x",
		newcMagic,
		inode,
		entry.mode,
		uint32(0), // uid
		uint32(0), // gid
		nlink,
		uint32(0), // mtime
		uint32(len(entry.data)),
		uint32(0), // dev major
		uint32(0), // dev minor
		entry.rdevMajor,
		entry.rdevMinor,
		uint32(len(entry.name)+1),
		uint32(0), // checksum is always zero for newc
	)
	if len(header) != newcHeaderBytes {
		return fmt.Errorf("internal newc header length is %d", len(header))
	}
	if err := writeBytes(writer, []byte(header)); err != nil {
		return err
	}
	if err := writeBytes(writer, append([]byte(entry.name), 0)); err != nil {
		return err
	}
	if err := writePadding(writer, 4); err != nil {
		return err
	}
	if err := writeBytes(writer, entry.data); err != nil {
		return err
	}
	return writePadding(writer, 4)
}

type countingWriter struct {
	writer io.Writer
	bytes  uint64
}

func (writer *countingWriter) Write(data []byte) (int, error) {
	written, err := writer.writer.Write(data)
	if written > 0 {
		writer.bytes += uint64(written)
	}
	return written, err
}

func writePadding(writer *countingWriter, alignment uint64) error {
	if alignment == 0 {
		return errors.New("newc alignment is zero")
	}
	padding := (alignment - writer.bytes%alignment) % alignment
	if padding == 0 {
		return nil
	}
	return writeBytes(writer, make([]byte, padding))
}

func writeBytes(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		if written <= 0 || written > len(data) {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}
