package mcpoperation

import (
	"fmt"
	"io"
	"os"
	"syscall"
)

// LoadConfigFile opens one operator-owned direct file without following a
// replacement between inspection and read. It is shared by the direct stdio
// server and the long-lived host transport.
func LoadConfigFile(path string) (Config, error) {
	pathInfo, err := os.Lstat(path)
	if err != nil {
		return Config{}, err
	}
	if !pathInfo.Mode().IsRegular() || pathInfo.Mode().Perm()&0o022 != 0 {
		return Config{}, fmt.Errorf("MCP Operation config %q must be a direct regular file not writable by group or others", path)
	}
	stat, ok := pathInfo.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() {
		return Config{}, fmt.Errorf("MCP Operation config %q must be owned by the current user", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return Config{}, err
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(pathInfo, opened) {
		return Config{}, fmt.Errorf("MCP Operation config %q changed while it was opened", path)
	}
	data, err := io.ReadAll(io.LimitReader(file, MaxConfigBytes+1))
	if err != nil {
		return Config{}, fmt.Errorf("read MCP Operation config: %w", err)
	}
	return ParseConfig(data)
}
