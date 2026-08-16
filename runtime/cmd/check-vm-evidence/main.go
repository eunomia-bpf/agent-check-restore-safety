// Command check-vm-evidence independently validates a retained VM demo run.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/vmevidence"
)

func main() {
	var directory string
	flag.StringVar(&directory, "evidence", "", "private directory retained by vm-demo -keep")
	flag.Parse()
	if directory == "" || flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "usage: check-vm-evidence -evidence /path/to/safe-change-vm-directory")
		os.Exit(2)
	}
	report, err := vmevidence.Check(directory)
	if err != nil {
		fmt.Fprintf(os.Stderr, "VM evidence rejected: %v\n", err)
		os.Exit(1)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(report); err != nil {
		fmt.Fprintf(os.Stderr, "encode VM evidence report: %v\n", err)
		os.Exit(1)
	}
}
