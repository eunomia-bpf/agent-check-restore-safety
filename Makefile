.PHONY: runtime-build runtime-test runtime-certcheck runtime-demo runtime-microservice-demo runtime-vm-demo runtime-codex-demo runtime-codex-isolated-demo runtime-codex-isolated-check runtime-integrated-demo runtime-integrated-check runtime-deathstar-demo runtime-deathstar-check runtime-verify

VM_ACCEL ?= tcg
CODEX_ISOLATED_EVIDENCE ?= docs/tmp/bootstrap/step-0013-20260815T124944Z
INTEGRATED_EVIDENCE ?= docs/tmp/bootstrap/step-0014-20260815T133621Z
DEATHSTAR_EVIDENCE ?= docs/tmp/bootstrap/step-0015-20260815T141250Z

runtime-build:
	cd runtime && go build ./...

runtime-test:
	cd runtime && go test ./...

runtime-certcheck:
	cd runtime && go test ./internal/certcheck ./cmd/check-certificate

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

# Stronger explicit live-account target: Codex and payment share no network.
runtime-codex-isolated-demo:
	python3 -m adapter.codex_isolated_runtime_demo $(CODEX_ISOLATED_DEMO_ARGS)

runtime-codex-isolated-check:
	python3 -m adapter.check_codex_isolated_evidence \
		"$(CODEX_ISOLATED_EVIDENCE)" --runtime-dir runtime

# Explicit live-account + full-VM target. All actors share one History.
runtime-integrated-demo:
	python3 -m adapter.codex_integrated_runtime_demo \
		--vm-accel "$(VM_ACCEL)" $(INTEGRATED_DEMO_ARGS)

runtime-integrated-check:
	python3 -m adapter.check_codex_integrated_evidence \
		"$(INTEGRATED_EVIDENCE)" --runtime-dir runtime

# Explicit real-application target. It builds and starts the complete pinned
# DeathStarBench graph and is intentionally not part of runtime-verify.
runtime-deathstar-demo:
	bash runtime/deploy/deathstar/run.sh

runtime-deathstar-check:
	python3 -m adapter.check_deathstar_evidence \
		"$(DEATHSTAR_EVIDENCE)" --runtime-dir runtime

runtime-verify:
	cd runtime && go build ./...
	cd runtime && go test -race ./...
	cd runtime && go vet ./...
	python3 -m unittest \
		adapter.test_docker_codex \
		adapter.test_codex_isolated_runtime_demo \
		adapter.test_check_codex_isolated_evidence \
		adapter.test_codex_integrated_runtime_demo \
		adapter.test_check_codex_integrated_evidence \
		adapter.test_check_deathstar_evidence
	$(MAKE) runtime-codex-isolated-check
	$(MAKE) runtime-integrated-check
	$(MAKE) runtime-deathstar-check
