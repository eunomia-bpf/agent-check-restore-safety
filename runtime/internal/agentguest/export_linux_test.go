//go:build linux

package agentguest

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
)

func TestExportRepositorySendsCompleteCanonicalTreeOnFixedPort(t *testing.T) {
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "result.txt"), []byte("done\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	stream := &memoryStream{}
	bundle, err := exportRepository(source, func(port uint32) (Stream, error) {
		if port != DefaultExportPort {
			t.Fatalf("export port = %d, want %d", port, DefaultExportPort)
		}
		return stream, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := repobundle.Decode(bytes.NewReader(stream.Bytes()), repobundle.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if decoded.TreeRoot != bundle.TreeRoot || len(decoded.Entries) != 1 || decoded.Entries[0].Path != "result.txt" {
		t.Fatalf("exported repository = %+v", decoded)
	}
}

type memoryStream struct {
	bytes.Buffer
	closed bool
}

func (stream *memoryStream) Read(data []byte) (int, error) {
	if stream.closed && stream.Len() == 0 {
		return 0, io.EOF
	}
	return stream.Buffer.Read(data)
}

func (stream *memoryStream) Close() error {
	stream.closed = true
	return nil
}
