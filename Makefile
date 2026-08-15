.PHONY: runtime-build runtime-test runtime-demo runtime-microservice-demo runtime-vm-demo runtime-codex-demo runtime-verify

VM_ACCEL ?= tcg

runtime-build:
	cd runtime && go build ./...

runtime-test:
	cd runtime && go test ./...

runtime-demo:
	@runtime_demo_dir="$$(mktemp -d)"; \
	cd runtime && go run ./cmd/demo \
		-history "$$runtime_demo_dir/runtime.history" \
		-sink "$$runtime_demo_dir/payment.history"

runtime-microservice-demo:
	bash runtime/deploy/microservice/run.sh

runtime-vm-demo:
	cd runtime && go run ./cmd/vm-demo -accel "$(VM_ACCEL)"

# Explicit live-account target. It is intentionally not part of runtime-verify.
runtime-codex-demo:
	python3 -m adapter.codex_runtime_demo $(CODEX_DEMO_ARGS)

runtime-verify:
	cd runtime && go build ./...
	cd runtime && go test -race ./...
	cd runtime && go vet ./...
