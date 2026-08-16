// Package agentwire defines the bounded framing protocol that carries an
// agentstream transcript over Firecracker vsock.
package agentwire

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentstream"
)

const MaxMessageBytes = 24 << 20

const (
	TypeRole       = "role"
	TypeAdvance    = "advance"
	TypeHello      = "hello"
	TypeAttach     = "attach"
	TypeFrame      = "frame"
	TypeBarrier    = "barrier"
	TypeBarrierAck = "barrier_ack"
)

// Message is a tagged union. Validate requires exactly the fields belonging
// to Type, preventing ignored fields from carrying a second interpretation.
type Message struct {
	Type         string               `json:"type"`
	Generation   uint64               `json:"generation,omitempty"`
	Hello        *agentstream.Hello   `json:"hello,omitempty"`
	Attach       *agentstream.Attach  `json:"attach,omitempty"`
	Frame        *agentstream.Frame   `json:"frame,omitempty"`
	Barrier      *agentstream.Barrier `json:"barrier,omitempty"`
	HostBarrier  *agentstream.Barrier `json:"host_barrier,omitempty"`
	GuestBarrier *agentstream.Barrier `json:"guest_barrier,omitempty"`
}

func (message Message) Validate() error {
	pointers := 0
	for _, present := range []bool{message.Hello != nil, message.Attach != nil, message.Frame != nil, message.Barrier != nil, message.HostBarrier != nil, message.GuestBarrier != nil} {
		if present {
			pointers++
		}
	}
	switch message.Type {
	case TypeRole:
		if message.Generation == 0 || pointers != 0 {
			return errors.New("agentwire role requires only a positive generation")
		}
	case TypeAdvance:
		if message.Generation == 0 || message.HostBarrier == nil || message.GuestBarrier == nil || pointers != 2 {
			return errors.New("agentwire advance requires generation and both barriers")
		}
	case TypeHello:
		if message.Generation != 0 || message.Hello == nil || pointers != 1 {
			return errors.New("agentwire hello requires only hello")
		}
	case TypeAttach:
		if message.Generation != 0 || message.Attach == nil || pointers != 1 {
			return errors.New("agentwire attach requires only attach")
		}
	case TypeFrame:
		if message.Generation != 0 || message.Frame == nil || pointers != 1 {
			return errors.New("agentwire frame requires only frame")
		}
	case TypeBarrier, TypeBarrierAck:
		if message.Generation != 0 || message.Barrier == nil || pointers != 1 {
			return fmt.Errorf("agentwire %s requires only barrier", message.Type)
		}
	default:
		return fmt.Errorf("agentwire message has unknown type %q", message.Type)
	}
	return nil
}

// Reader consumes complete JSON objects without retaining an unbounded line.
type Reader struct {
	reader *bufio.Reader
}

func NewReader(reader io.Reader) (*Reader, error) {
	if reader == nil {
		return nil, errors.New("agentwire reader is nil")
	}
	return &Reader{reader: bufio.NewReaderSize(reader, 64<<10)}, nil
}

func (reader *Reader) Read() (Message, error) {
	line, err := readBoundedLine(reader.reader, MaxMessageBytes)
	if err != nil {
		return Message{}, err
	}
	if err := rejectDuplicateJSONKeys(line); err != nil {
		return Message{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.DisallowUnknownFields()
	var message Message
	if err := decoder.Decode(&message); err != nil {
		return Message{}, fmt.Errorf("decode agentwire message: %w", err)
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return Message{}, fmt.Errorf("agentwire message has trailing value %v", token)
		}
		return Message{}, fmt.Errorf("agentwire message has trailing data: %w", err)
	}
	if err := message.Validate(); err != nil {
		return Message{}, err
	}
	return message, nil
}

// Writer serializes complete messages so concurrent transcript and barrier
// events can never interleave bytes.
type Writer struct {
	mu     sync.Mutex
	writer io.Writer
}

func NewWriter(writer io.Writer) (*Writer, error) {
	if writer == nil {
		return nil, errors.New("agentwire writer is nil")
	}
	return &Writer{writer: writer}, nil
}

func (writer *Writer) Write(message Message) error {
	if err := message.Validate(); err != nil {
		return err
	}
	encoded, err := json.Marshal(message)
	if err != nil {
		return fmt.Errorf("encode agentwire message: %w", err)
	}
	if len(encoded) > MaxMessageBytes {
		return fmt.Errorf("agentwire message exceeds %d bytes", MaxMessageBytes)
	}
	encoded = append(encoded, '\n')
	writer.mu.Lock()
	defer writer.mu.Unlock()
	return writeAll(writer.writer, encoded)
}

func readBoundedLine(reader *bufio.Reader, limit int) ([]byte, error) {
	var line []byte
	for {
		fragment, err := reader.ReadSlice('\n')
		if len(line) > limit-len(fragment) {
			return nil, fmt.Errorf("agentwire message exceeds %d bytes", limit)
		}
		line = append(line, fragment...)
		if err == nil {
			if len(line) == 1 {
				return nil, errors.New("agentwire message is empty")
			}
			return line[:len(line)-1], nil
		}
		if !errors.Is(err, bufio.ErrBufferFull) {
			return nil, err
		}
	}
}

func writeAll(writer io.Writer, data []byte) error {
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

func rejectDuplicateJSONKeys(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := validateValue(decoder); err != nil {
		return fmt.Errorf("invalid agentwire JSON: %w", err)
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return fmt.Errorf("invalid agentwire JSON: trailing value %v", token)
		}
		return fmt.Errorf("invalid agentwire JSON: trailing data: %w", err)
	}
	return nil
}

// CanonicalJSONObject rejects duplicate keys and trailing data, then returns
// one compact object with recursively sorted keys. It is used only for
// cross-boundary evidence commitments; the framed protocol retains its exact
// original bytes.
func CanonicalJSONObject(data []byte) ([]byte, error) {
	if err := rejectDuplicateJSONKeys(data); err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, fmt.Errorf("decode canonical JSON object: %w", err)
	}
	if _, ok := value.(map[string]any); !ok {
		return nil, errors.New("canonical JSON value is not an object")
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, fmt.Errorf("canonical JSON object has trailing value %v", token)
		}
		return nil, fmt.Errorf("canonical JSON object has trailing data: %w", err)
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return nil, fmt.Errorf("encode canonical JSON object: %w", err)
	}
	return encoded, nil
}

func validateValue(decoder *json.Decoder) error {
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, compound := token.(json.Delim)
	if !compound {
		return nil
	}
	switch delimiter {
	case '{':
		seen := make(map[string]struct{})
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return err
			}
			key, ok := keyToken.(string)
			if !ok {
				return errors.New("object key is not a string")
			}
			if _, exists := seen[key]; exists {
				return fmt.Errorf("duplicate object key %q", key)
			}
			seen[key] = struct{}{}
			if err := validateValue(decoder); err != nil {
				return err
			}
		}
		closing, err := decoder.Token()
		if err != nil {
			return err
		}
		if value, ok := closing.(json.Delim); !ok || value != '}' {
			return errors.New("object is not closed")
		}
		return nil
	case '[':
		for decoder.More() {
			if err := validateValue(decoder); err != nil {
				return err
			}
		}
		closing, err := decoder.Token()
		if err != nil {
			return err
		}
		if value, ok := closing.(json.Delim); !ok || value != ']' {
			return errors.New("array is not closed")
		}
		return nil
	default:
		return fmt.Errorf("unexpected delimiter %q", delimiter)
	}
}
