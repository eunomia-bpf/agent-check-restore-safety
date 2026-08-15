package main

import (
	"log"
	"os"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/workerapp"
)

func main() {
	if err := workerapp.Run(
		os.Getenv("TEMPORAL_ADDRESS"),
		os.Getenv("PAYMENT_URL"),
		os.Getenv("COMPLETION_URL"),
	); err != nil {
		log.Fatal(err)
	}
}
