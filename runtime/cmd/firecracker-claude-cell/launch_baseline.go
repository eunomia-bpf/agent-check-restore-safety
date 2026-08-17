//go:build !historyguard

package main

import (
	"context"
)

func registerLaunchFlags(*options) {}

func validateLaunchOptions(config options) error { return nil }

func launchOptionPaths(*options) []*string { return nil }

func launchConfiguredCell(ctx context.Context, _ options, inputs launchInputs) (launchResult, error) {
	if err := inputs.client.Start(ctx); err != nil {
		return launchResult{}, err
	}
	return launchResult{Guarded: false, Decision: "baseline-unguarded", Started: true}, nil
}
