// check-certificate is the non-privileged, read-only Certificate checker.
// It accepts a versioned Certificate State projection and a Certificate as
// separate JSON files and never imports the compiler or the control service.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/certcheck"
)

type output struct {
	certcheck.Verdict
	Error string `json:"error,omitempty"`
}

func readDocument(path string) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	contents, err := io.ReadAll(io.LimitReader(file, certcheck.MaxDocumentBytes+1))
	if err != nil {
		return nil, err
	}
	if len(contents) > certcheck.MaxDocumentBytes {
		return nil, fmt.Errorf("JSON document exceeds %d bytes", certcheck.MaxDocumentBytes)
	}
	return contents, nil
}

func writeOutput(writer io.Writer, value output) error {
	encoder := json.NewEncoder(writer)
	encoder.SetEscapeHTML(false)
	return encoder.Encode(value)
}

func run(arguments []string, stdout, stderr io.Writer) int {
	flags := flag.NewFlagSet("check-certificate", flag.ContinueOnError)
	flags.SetOutput(stderr)
	var statePath string
	var certificatePath string
	flags.StringVar(&statePath, "state", "", "versioned Certificate State projection JSON")
	flags.StringVar(&certificatePath, "certificate", "", "Certificate JSON")
	if err := flags.Parse(arguments); err != nil {
		return 2
	}
	if statePath == "" || certificatePath == "" || flags.NArg() != 0 {
		fmt.Fprintln(stderr, "usage: check-certificate -state STATE.json -certificate CERTIFICATE.json")
		return 2
	}
	stateJSON, err := readDocument(statePath)
	if err == nil {
		var certificateJSON []byte
		certificateJSON, err = readDocument(certificatePath)
		if err == nil {
			var verdict certcheck.Verdict
			verdict, err = certcheck.CheckJSON(stateJSON, certificateJSON)
			if err == nil {
				if writeErr := writeOutput(stdout, output{Verdict: verdict}); writeErr != nil {
					fmt.Fprintln(stderr, writeErr)
					return 1
				}
				return 0
			}
		}
	}
	if err == nil {
		err = errors.New("Certificate check failed")
	}
	if writeErr := writeOutput(stdout, output{Verdict: certcheck.Verdict{Valid: false}, Error: err.Error()}); writeErr != nil {
		fmt.Fprintln(stderr, writeErr)
	}
	return 1
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}
