//go:build linux

package agentguest

import (
	"errors"
	"fmt"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
)

// ExportRepository sends the complete final tree only after the caller has
// emptied the execution domain. A complete tree, rather than an agent-authored
// patch, lets the host derive and verify deletions independently.
func ExportRepository(dial func(uint32) (Stream, error)) (repobundle.Bundle, error) {
	return exportRepository(WorkspaceDirectory, dial)
}

func exportRepository(source string, dial func(uint32) (Stream, error)) (repobundle.Bundle, error) {
	if dial == nil {
		return repobundle.Bundle{}, errors.New("repository export dialer is nil")
	}
	stream, err := dial(DefaultExportPort)
	if err != nil {
		return repobundle.Bundle{}, fmt.Errorf("dial repository export endpoint: %w", err)
	}
	if stream == nil {
		return repobundle.Bundle{}, errors.New("repository export dialer returned nil stream")
	}
	bundle, buildErr := repobundle.Build(source, stream, repobundle.DefaultLimits())
	closeErr := stream.Close()
	if err := errors.Join(buildErr, closeErr); err != nil {
		return repobundle.Bundle{}, fmt.Errorf("export final repository: %w", err)
	}
	return bundle, nil
}
