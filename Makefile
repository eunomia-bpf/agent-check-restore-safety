.PHONY: safe-change-demo runtime-build runtime-test runtime-certcheck runtime-image runtime-starter-check runtime-demo runtime-microservice-demo runtime-vm-demo runtime-vm-check runtime-firecracker-source-check runtime-firecracker-fetch runtime-firecracker-build runtime-firecracker-preflight runtime-firecracker-production-preflight runtime-firecracker-kvm-test runtime-firecracker-check runtime-firecracker-codex-build runtime-firecracker-codex-payload runtime-firecracker-codex-repository runtime-firecracker-codex-demo runtime-firecracker-codex-check runtime-codex-demo runtime-codex-isolated-demo runtime-codex-isolated-check runtime-integrated-demo runtime-integrated-check runtime-deathstar-demo runtime-deathstar-check runtime-verify

VM_ACCEL ?= tcg
VM_BACKEND ?= qemu
VM_DEMO_ARGS ?=
VM_EVIDENCE ?=
FIRECRACKER_EVIDENCE ?=
FIRECRACKER_KVM_TEST_ARGS ?=
FIRECRACKER_PREFLIGHT_ARGS ?=
FIRECRACKER_PRODUCTION_PREFLIGHT_ARGS ?=
FIRECRACKER_BUILD_DIR ?= $(shell python3 -c 'import os; print(os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safe-change-runtime", "firecracker", "build"))')
FIRECRACKER_FETCH_INPUTS := runtime/deploy/firecracker/assets.lock.json runtime/deploy/firecracker/fetch-assets.sh
FIRECRACKER_CODEX_DEMO_ARGS ?=
FIRECRACKER_CODEX_PAYLOAD_ARGS ?=
FIRECRACKER_CODEX_REPOSITORY_ARGS ?=
FIRECRACKER_CODEX_EVIDENCE ?=
FIRECRACKER_CODEX_ADAPTER_EVIDENCE ?=
FIRECRACKER_CODEX_PAYLOAD ?=
FIRECRACKER_CODEX_PAYLOAD_RESULT ?=
FIRECRACKER_CODEX_RUNNER ?=
RUNTIME_IMAGE ?= safe-change-runtime:local
RUNTIME_VERSION ?= dev
RUNTIME_REVISION ?= $(shell git rev-parse --short=12 HEAD)
CODEX_ISOLATED_EVIDENCE ?= docs/tmp/bootstrap/step-0013-20260815T124944Z
INTEGRATED_EVIDENCE ?= docs/tmp/bootstrap/step-0018-20260816T125801Z
DEATHSTAR_EVIDENCE ?= docs/tmp/bootstrap/step-0015-20260815T141250Z

runtime-build:
	cd runtime && go build ./...

runtime-test:
	cd runtime && go test ./...

runtime-certcheck:
	cd runtime && go test ./internal/certcheck ./cmd/check-certificate

runtime-image:
	docker build \
		--build-arg VERSION="$(RUNTIME_VERSION)" \
		--build-arg REVISION="$(RUNTIME_REVISION)" \
		-f runtime/deploy/image/Dockerfile \
		-t "$(RUNTIME_IMAGE)" runtime

runtime-starter-check:
	bash runtime/deploy/starter/check.sh

runtime-demo:
	@runtime_demo_dir="$$(mktemp -d)"; \
	cd runtime && go run ./cmd/demo \
		-history "$$runtime_demo_dir/runtime.history" \
		-sink "$$runtime_demo_dir/payment.history"

safe-change-demo: runtime-microservice-demo

runtime-microservice-demo:
	bash runtime/deploy/microservice/run.sh

runtime-vm-demo:
	cd runtime && go run ./cmd/vm-demo -accel "$(VM_ACCEL)" $(VM_DEMO_ARGS)

runtime-vm-check:
	@test -n "$(strip $(VM_EVIDENCE))" || { echo "VM_EVIDENCE must name a retained VM evidence directory" >&2; exit 2; }
	cd runtime && go run ./cmd/check-vm-evidence -evidence "$(abspath $(VM_EVIDENCE))"

# Fetches only checksum-pinned Firecracker v1.16.1 and guest-kernel assets.
# This target does not open /dev/kvm or start a microVM.
runtime-firecracker-source-check:
	@for firecracker_input in $(FIRECRACKER_FETCH_INPUTS); do \
		test -f "$$firecracker_input" && test ! -L "$$firecracker_input" || { \
			echo "$$firecracker_input must be a direct regular file" >&2; \
			exit 2; \
		}; \
		expected_hash="$$(git rev-parse --verify "HEAD:$$firecracker_input" 2>/dev/null)" || { \
			echo "$$firecracker_input must be committed before the Firecracker fetcher can run" >&2; \
			exit 2; \
		}; \
		actual_hash="$$(git hash-object --no-filters "$$firecracker_input")" || exit 2; \
		test "$$actual_hash" = "$$expected_hash" || { \
			echo "$$firecracker_input bytes do not match HEAD" >&2; \
			exit 2; \
		}; \
	done
	@test -z "$$(git status --porcelain=v1 --untracked-files=all -- $(FIRECRACKER_FETCH_INPUTS))" || { \
		echo "Firecracker fetch inputs must match HEAD before execution" >&2; \
		git status --short -- $(FIRECRACKER_FETCH_INPUTS) >&2; \
		exit 2; \
	}

runtime-firecracker-fetch: runtime-firecracker-source-check
	bash runtime/deploy/firecracker/fetch-assets.sh

runtime-firecracker-build:
	@mkdir -p "$(FIRECRACKER_BUILD_DIR)"
	@chmod 0700 "$(FIRECRACKER_BUILD_DIR)"
	cd runtime && CGO_ENABLED=0 go build -trimpath \
		-o "$(FIRECRACKER_BUILD_DIR)/firecracker-guest" ./cmd/firecracker-guest
	cd runtime && CGO_ENABLED=0 go build -trimpath \
		-o "$(FIRECRACKER_BUILD_DIR)/firecracker-demo" ./cmd/firecracker-demo
	@chmod 0500 \
		"$(FIRECRACKER_BUILD_DIR)/firecracker-guest" \
		"$(FIRECRACKER_BUILD_DIR)/firecracker-demo"
	@printf '%s\n' \
		"FIRECRACKER_GUEST=$(FIRECRACKER_BUILD_DIR)/firecracker-guest" \
		"FIRECRACKER_RUNNER=$(FIRECRACKER_BUILD_DIR)/firecracker-demo"

# Read-only admission checks. Fetch/build are separate so a failed preflight
# never fixes or hides the condition it was asked to report.
runtime-firecracker-preflight:
	@cd runtime && go run ./cmd/firecracker-preflight \
		-level prototype \
		-guest "$(abspath $(FIRECRACKER_BUILD_DIR)/firecracker-guest)" $(FIRECRACKER_PREFLIGHT_ARGS)

# This remains NOT READY until the runner itself launches only through jailer.
runtime-firecracker-production-preflight:
	@cd runtime && go run ./cmd/firecracker-preflight \
		-level production \
		-guest "$(abspath $(FIRECRACKER_BUILD_DIR)/firecracker-guest)" $(FIRECRACKER_PRODUCTION_PREFLIGHT_ARGS)

# Explicit real-KVM integration test. It is intentionally excluded from
# runtime-verify so ordinary builds never acquire hardware virtualization.
runtime-firecracker-kvm-test: runtime-firecracker-fetch runtime-firecracker-build
	@test -c /dev/kvm || { echo "/dev/kvm is missing or is not a character device" >&2; exit 2; }
	@test -r /dev/kvm && test -w /dev/kvm || { echo "Firecracker requires read/write access to /dev/kvm; refresh the kvm group or run: sg kvm -c 'make runtime-firecracker-kvm-test'" >&2; exit 2; }
	cd runtime && FIRECRACKER_KVM_INTEGRATION=1 go test -count=1 -v \
		-run '^TestFirecrackerKVMRestore$$' ./cmd/firecracker-demo \
		$(FIRECRACKER_KVM_TEST_ARGS)

runtime-firecracker-check:
	@test -n "$(strip $(FIRECRACKER_EVIDENCE))" || { echo "FIRECRACKER_EVIDENCE must name a retained Firecracker evidence directory" >&2; exit 2; }
	cd runtime && go run ./cmd/check-firecracker-evidence \
		-evidence "$(abspath $(FIRECRACKER_EVIDENCE))"

# Explicit Firecracker + Codex slice. These targets do not fetch Firecracker
# or kernel assets, and the real-KVM demo is excluded from runtime-verify.
runtime-firecracker-codex-build:
	@mkdir -p "$(FIRECRACKER_BUILD_DIR)"
	@chmod 0700 "$(FIRECRACKER_BUILD_DIR)"
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(FIRECRACKER_BUILD_DIR)/firecracker-agent-guest" ./cmd/firecracker-agent-guest
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(FIRECRACKER_BUILD_DIR)/firecracker-codex-shim" ./cmd/firecracker-codex-shim
	@chmod 0500 \
		"$(FIRECRACKER_BUILD_DIR)/firecracker-agent-guest" \
		"$(FIRECRACKER_BUILD_DIR)/firecracker-codex-shim"
	@sha256sum \
		"$(FIRECRACKER_BUILD_DIR)/firecracker-agent-guest" \
		"$(FIRECRACKER_BUILD_DIR)/firecracker-codex-shim"

runtime-firecracker-codex-payload:
	cd runtime && go run ./cmd/firecracker-codex-payload \
		$(FIRECRACKER_CODEX_PAYLOAD_ARGS)

runtime-firecracker-codex-repository:
	cd runtime && go run ./cmd/firecracker-codex-repository \
		$(FIRECRACKER_CODEX_REPOSITORY_ARGS)

runtime-firecracker-codex-demo:
	@test -c /dev/kvm || { echo "/dev/kvm is missing or is not a character device" >&2; exit 2; }
	@test -r /dev/kvm && test -w /dev/kvm || { echo "Firecracker Codex demo requires read/write access to /dev/kvm" >&2; exit 2; }
	python3 -m adapter.firecracker_codex_runtime_demo \
		$(FIRECRACKER_CODEX_DEMO_ARGS)

runtime-firecracker-codex-check:
	@test -n "$(strip $(FIRECRACKER_CODEX_EVIDENCE))" || { echo "FIRECRACKER_CODEX_EVIDENCE must name the retained runtime evidence directory" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_ADAPTER_EVIDENCE))" || { echo "FIRECRACKER_CODEX_ADAPTER_EVIDENCE must name the retained adapter evidence directory" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_PAYLOAD))" || { echo "FIRECRACKER_CODEX_PAYLOAD must name the retained payload image" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_PAYLOAD_RESULT))" || { echo "FIRECRACKER_CODEX_PAYLOAD_RESULT must name the retained payload result" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_RUNNER))" || { echo "FIRECRACKER_CODEX_RUNNER must name the exact retained shim executable" >&2; exit 2; }
	cd runtime && go run ./cmd/check-firecracker-codex-evidence \
		-evidence "$(abspath $(FIRECRACKER_CODEX_EVIDENCE))" \
		-adapter-jsonl "$(abspath $(FIRECRACKER_CODEX_ADAPTER_EVIDENCE))/app-server.jsonl" \
		-payload "$(abspath $(FIRECRACKER_CODEX_PAYLOAD))" \
		-payload-result "$(abspath $(FIRECRACKER_CODEX_PAYLOAD_RESULT))" \
		-runner "$(abspath $(FIRECRACKER_CODEX_RUNNER))"

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
ifeq ($(VM_BACKEND),firecracker)
runtime-integrated-demo: runtime-firecracker-fetch
endif
runtime-integrated-demo:
	python3 -I -c 'import runpy,sys; sys.path.insert(0,"$(CURDIR)"); runpy.run_module("adapter.codex_integrated_runtime_demo",run_name="__main__")' \
		--vm-backend "$(VM_BACKEND)" --vm-accel "$(VM_ACCEL)" $(INTEGRATED_DEMO_ARGS)

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
		adapter.test_firecracker_codex \
		adapter.test_firecracker_codex_runtime_demo \
		adapter.test_codex_isolated_runtime_demo \
		adapter.test_check_codex_isolated_evidence \
		adapter.test_codex_integrated_runtime_demo \
		adapter.test_check_codex_integrated_evidence \
		adapter.test_check_deathstar_evidence
	$(MAKE) runtime-codex-isolated-check
	$(MAKE) runtime-integrated-check
	$(MAKE) runtime-deathstar-check
