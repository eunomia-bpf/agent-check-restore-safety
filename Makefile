.PHONY: safe-change-demo runtime-build runtime-test runtime-certcheck runtime-image runtime-starter-check runtime-demo runtime-microservice-demo runtime-vm-demo runtime-vm-check runtime-qemu-agent-restore-build runtime-qemu-agent-restore-preflight runtime-qemu-agent-restore-admit runtime-qemu-agent-restore-demo runtime-qemu-agent-restore-check runtime-firecracker-source-check runtime-firecracker-fetch runtime-firecracker-build runtime-firecracker-preflight runtime-firecracker-production-preflight runtime-firecracker-kvm-test runtime-firecracker-check runtime-firecracker-codex-build runtime-firecracker-codex-payload runtime-firecracker-codex-repository runtime-firecracker-codex-demo runtime-firecracker-codex-mcp-demo runtime-firecracker-codex-mcp-inflight-demo runtime-firecracker-codex-mcp-check runtime-firecracker-codex-check runtime-firecracker-codex-control-check runtime-firecracker-claude-build runtime-firecracker-claude-payload runtime-firecracker-claude-demo runtime-firecracker-claude-check runtime-firecracker-deathstar-build runtime-firecracker-deathstar-payload runtime-firecracker-deathstar-demo runtime-firecracker-deathstar-check runtime-mcp-operation-build runtime-mcp-operation-check runtime-mcp-operation-demo runtime-codex-mcp-build runtime-codex-mcp-demo runtime-codex-mcp-docker-demo runtime-codex-mcp-check runtime-claude-source-check runtime-claude-fetch runtime-claude-mcp-demo runtime-claude-mcp-check runtime-codex-demo runtime-codex-isolated-demo runtime-codex-isolated-check runtime-integrated-demo runtime-integrated-check runtime-deathstar-demo runtime-deathstar-check runtime-verify

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
FIRECRACKER_CODEX_MCP_DEMO_ARGS ?=
FIRECRACKER_CODEX_MCP_INFLIGHT_DEMO_ARGS ?=
FIRECRACKER_CODEX_PAYLOAD_ARGS ?=
FIRECRACKER_CODEX_REPOSITORY_ARGS ?=
FIRECRACKER_CODEX_EVIDENCE ?=
FIRECRACKER_CODEX_ADAPTER_EVIDENCE ?=
FIRECRACKER_CODEX_PAYLOAD ?=
FIRECRACKER_CODEX_PAYLOAD_RESULT ?=
FIRECRACKER_CODEX_RUNNER ?=
FIRECRACKER_CODEX_CONTROL_HISTORY ?=
FIRECRACKER_CODEX_HEAD_ANCHOR ?=
FIRECRACKER_CODEX_PAYMENT_HISTORY ?=
FIRECRACKER_CODEX_WORKLOAD_CONTRACT ?=
FIRECRACKER_CLAUDE_BUILD_DIR ?= $(shell python3 -c 'import os; print(os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safe-change-runtime", "firecracker-claude"))')
FIRECRACKER_CLAUDE_CELL ?= $(FIRECRACKER_CLAUDE_BUILD_DIR)/firecracker-claude-cell
FIRECRACKER_CLAUDE_GUEST ?= $(FIRECRACKER_CLAUDE_BUILD_DIR)/firecracker-claude-guest
FIRECRACKER_CLAUDE_PAYLOAD ?= $(FIRECRACKER_CLAUDE_BUILD_DIR)/claude-payload.squashfs
FIRECRACKER_CLAUDE_PAYLOAD_RESULT ?= $(FIRECRACKER_CLAUDE_BUILD_DIR)/claude-payload.json
FIRECRACKER_CLAUDE_DEMO_ARGS ?=
FIRECRACKER_CLAUDE_EVIDENCE ?=
FIRECRACKER_DEATHSTAR_PAYLOAD ?= $(FIRECRACKER_CLAUDE_BUILD_DIR)/claude-http-v4-payload.squashfs
FIRECRACKER_DEATHSTAR_PAYLOAD_RESULT ?= $(FIRECRACKER_CLAUDE_BUILD_DIR)/claude-http-v4-payload.json
FIRECRACKER_DEATHSTAR_BASH ?= /bin/bash
FIRECRACKER_DEATHSTAR_BASH_LIBRARY ?= $(shell readlink -f /lib/x86_64-linux-gnu/libtinfo.so.6)
FIRECRACKER_DEATHSTAR_EVIDENCE ?= docs/tmp/bootstrap/step-0022-20260817T025925Z/experiment-firecracker-deathstar-egress/raw
FIRECRACKER_DEATHSTAR_REPETITIONS ?= 3
MCP_OPERATION_BUILD_DIR ?= $(shell python3 -c 'import os; print(os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safe-change-runtime", "mcp-operation"))')
MCP_RELAY_BUNDLE_DIR ?= $(MCP_OPERATION_BUILD_DIR)/relay-bundle
CODEX_MCP_DEMO_ARGS ?=
CODEX_MCP_DOCKER_ARGS ?=
CODEX_MCP_EVIDENCE ?=
CLAUDE_CODE_LOCK := runtime/deploy/claude-code/assets.lock.json
CLAUDE_CODE_FETCH_INPUTS := $(CLAUDE_CODE_LOCK) runtime/deploy/claude-code/fetch-assets.sh
CLAUDE_CODE_CACHE_ROOT ?= $(shell python3 -c 'import os; print(os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safe-change-runtime", "claude"))')
CLAUDE_CODE_BINARY ?= $(CLAUDE_CODE_CACHE_ROOT)/2.1.233/claude
CLAUDE_CODE_SHA256 ?= 55d281096f57d411ebbdd94dbf5e9ff3accb7c05713e37348c2c11d4b83bf9d9
CLAUDE_MCP_DEMO_ARGS ?=
CLAUDE_MCP_EVIDENCE ?=
RUNTIME_IMAGE ?= safe-change-runtime:local
RUNTIME_VERSION ?= dev
RUNTIME_REVISION ?= $(shell git rev-parse --short=12 HEAD)
CODEX_ISOLATED_EVIDENCE ?= docs/tmp/bootstrap/step-0013-20260815T124944Z
INTEGRATED_EVIDENCE ?= docs/tmp/bootstrap/step-0018-20260816T125801Z
DEATHSTAR_EVIDENCE ?= docs/tmp/bootstrap/step-0015-20260815T141250Z
QEMU_AGENT_RESTORE_BUILD_DIR ?= $(shell python3 -c 'import os; print(os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safe-change-runtime", "qemu-agent-restore"))')
QEMU_AGENT_RESTORE_EVIDENCE ?= docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/raw
QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE ?= docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/preflight-attempt-1
QEMU_AGENT_RESTORE_PREFLIGHT_GATE ?= docs/tmp/bootstrap/step-0024-20260817T060908Z/experiment-qemu-agent-history-restore-execution/preflight-pass.json
QEMU_AGENT_RESTORE_REPETITIONS ?= 3
QEMU_AGENT_RESTORE_IMAGE ?= $(shell python3 -c 'import os; print(os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "safe-change-runtime", "images", "ubuntu-24.04-20260725-amd64.img"))')
QEMU_AGENT_RESTORE_IMAGE_SHA256 ?= d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac
QEMU_AGENT_RESTORE_ACCEL ?= kvm

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

runtime-qemu-agent-restore-build:
	@mkdir -p "$(QEMU_AGENT_RESTORE_BUILD_DIR)"
	@chmod 0700 "$(QEMU_AGENT_RESTORE_BUILD_DIR)"
	cd runtime && go build -trimpath -o "$(QEMU_AGENT_RESTORE_BUILD_DIR)/vm-demo" ./cmd/vm-demo
	cd runtime && go build -trimpath -o "$(QEMU_AGENT_RESTORE_BUILD_DIR)/control" ./cmd/control
	cd runtime && go build -trimpath -o "$(QEMU_AGENT_RESTORE_BUILD_DIR)/effect-proxy" ./cmd/effect-proxy
	cd runtime && go build -trimpath -o "$(QEMU_AGENT_RESTORE_BUILD_DIR)/deathstar-adapter" ./cmd/deathstar-adapter
	cd runtime && go build -trimpath -o "$(QEMU_AGENT_RESTORE_BUILD_DIR)/check-certificate" ./cmd/check-certificate
	@chmod 0500 "$(QEMU_AGENT_RESTORE_BUILD_DIR)/vm-demo" \
		"$(QEMU_AGENT_RESTORE_BUILD_DIR)/control" \
		"$(QEMU_AGENT_RESTORE_BUILD_DIR)/effect-proxy" \
		"$(QEMU_AGENT_RESTORE_BUILD_DIR)/deathstar-adapter" \
		"$(QEMU_AGENT_RESTORE_BUILD_DIR)/check-certificate"

runtime-qemu-agent-restore-preflight: runtime-qemu-agent-restore-build
	QEMU_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/vm-demo" \
	CLAUDE_BINARY="$(CLAUDE_CODE_BINARY)" CLAUDE_SHA256="$(CLAUDE_CODE_SHA256)" \
	CONTROL_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/control" \
	EFFECT_PROXY_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/effect-proxy" \
	DEATHSTAR_ADAPTER_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/deathstar-adapter" \
	UBUNTU_IMAGE="$(QEMU_AGENT_RESTORE_IMAGE)" UBUNTU_IMAGE_SHA256="$(QEMU_AGENT_RESTORE_IMAGE_SHA256)" \
	EVIDENCE_DIR="$(abspath $(QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE))" REPETITIONS=1 QEMU_ACCEL="$(QEMU_AGENT_RESTORE_ACCEL)" \
	bash runtime/deploy/qemu-agent-restore/run.sh

runtime-qemu-agent-restore-admit: runtime-qemu-agent-restore-build
	@test -n "$(strip $(QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE))" || { echo "QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE is required" >&2; exit 2; }
	@if test -e "$(abspath $(QEMU_AGENT_RESTORE_PREFLIGHT_GATE))"; then \
		python3 -I adapter/qemu_agent_restore_gate.py verify \
			--repo-root "$(CURDIR)" --gate "$(abspath $(QEMU_AGENT_RESTORE_PREFLIGHT_GATE))" \
			--checker "$(CURDIR)/adapter/check_qemu_agent_restore_evidence.py" \
			--certificate-checker "$(QEMU_AGENT_RESTORE_BUILD_DIR)/check-certificate"; \
	else \
		python3 -I adapter/qemu_agent_restore_gate.py create \
			--repo-root "$(CURDIR)" --evidence "$(abspath $(QEMU_AGENT_RESTORE_PREFLIGHT_EVIDENCE))" \
			--gate "$(abspath $(QEMU_AGENT_RESTORE_PREFLIGHT_GATE))" \
			--checker "$(CURDIR)/adapter/check_qemu_agent_restore_evidence.py" \
			--certificate-checker "$(QEMU_AGENT_RESTORE_BUILD_DIR)/check-certificate"; \
	fi

runtime-qemu-agent-restore-demo: runtime-qemu-agent-restore-build runtime-qemu-agent-restore-admit
	QEMU_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/vm-demo" \
	CLAUDE_BINARY="$(CLAUDE_CODE_BINARY)" CLAUDE_SHA256="$(CLAUDE_CODE_SHA256)" \
	CONTROL_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/control" \
	EFFECT_PROXY_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/effect-proxy" \
	DEATHSTAR_ADAPTER_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/deathstar-adapter" \
	CERTIFICATE_CHECKER_BINARY="$(QEMU_AGENT_RESTORE_BUILD_DIR)/check-certificate" \
	EVIDENCE_CHECKER="$(CURDIR)/adapter/check_qemu_agent_restore_evidence.py" \
	PREFLIGHT_GATE="$(abspath $(QEMU_AGENT_RESTORE_PREFLIGHT_GATE))" \
	UBUNTU_IMAGE="$(QEMU_AGENT_RESTORE_IMAGE)" UBUNTU_IMAGE_SHA256="$(QEMU_AGENT_RESTORE_IMAGE_SHA256)" \
	EVIDENCE_DIR="$(abspath $(QEMU_AGENT_RESTORE_EVIDENCE))" REPETITIONS="$(QEMU_AGENT_RESTORE_REPETITIONS)" QEMU_ACCEL="$(QEMU_AGENT_RESTORE_ACCEL)" \
	bash runtime/deploy/qemu-agent-restore/run.sh

runtime-qemu-agent-restore-check: runtime-qemu-agent-restore-build
	@test -n "$(strip $(QEMU_AGENT_RESTORE_EVIDENCE))" || { echo "QEMU_AGENT_RESTORE_EVIDENCE is required" >&2; exit 2; }
	python3 -I adapter/check_qemu_agent_restore_evidence.py \
		--evidence "$(abspath $(QEMU_AGENT_RESTORE_EVIDENCE))" \
		--certificate-checker "$(QEMU_AGENT_RESTORE_BUILD_DIR)/check-certificate"

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
	@test -r /dev/kvm && test -w /dev/kvm || { echo "Firecracker Codex demo requires read/write access to /dev/kvm; refresh the kvm group or run: sg kvm -c 'make runtime-firecracker-codex-demo ...'" >&2; exit 2; }
	python3 -m adapter.firecracker_codex_runtime_demo \
		$(FIRECRACKER_CODEX_DEMO_ARGS)

runtime-firecracker-codex-mcp-demo:
	@test -c /dev/kvm || { echo "/dev/kvm is missing or is not a character device" >&2; exit 2; }
	@test -r /dev/kvm && test -w /dev/kvm || { echo "Firecracker Codex MCP demo requires read/write access to /dev/kvm; refresh the kvm group or run: sg kvm -c 'make runtime-firecracker-codex-mcp-demo ...'" >&2; exit 2; }
	python3 -m adapter.firecracker_codex_mcp_runtime_demo \
		$(FIRECRACKER_CODEX_MCP_DEMO_ARGS)

runtime-firecracker-codex-mcp-inflight-demo:
	@test -c /dev/kvm || { echo "/dev/kvm is missing or is not a character device" >&2; exit 2; }
	@test -r /dev/kvm && test -w /dev/kvm || { echo "Firecracker Codex in-flight MCP demo requires read/write access to /dev/kvm" >&2; exit 2; }
	python3 -m adapter.firecracker_codex_mcp_runtime_demo \
		--checkpoint-mode inflight \
		$(FIRECRACKER_CODEX_MCP_INFLIGHT_DEMO_ARGS)

runtime-firecracker-codex-mcp-check:
	@test -n "$(strip $(FIRECRACKER_CODEX_MCP_EVIDENCE))" || { echo "FIRECRACKER_CODEX_MCP_EVIDENCE must name the retained combined evidence directory" >&2; exit 2; }
	$(MAKE) runtime-firecracker-codex-check \
		FIRECRACKER_CODEX_EVIDENCE="$(abspath $(FIRECRACKER_CODEX_MCP_EVIDENCE))/runtime" \
		FIRECRACKER_CODEX_ADAPTER_EVIDENCE="$(abspath $(FIRECRACKER_CODEX_MCP_EVIDENCE))/adapter" \
		FIRECRACKER_CODEX_PAYLOAD="$(FIRECRACKER_CODEX_PAYLOAD)" \
		FIRECRACKER_CODEX_PAYLOAD_RESULT="$(FIRECRACKER_CODEX_PAYLOAD_RESULT)" \
		FIRECRACKER_CODEX_RUNNER="$(FIRECRACKER_CODEX_RUNNER)"
	python3 -m adapter.check_firecracker_codex_mcp_evidence \
		"$(abspath $(FIRECRACKER_CODEX_MCP_EVIDENCE))" \
		"$(abspath $(FIRECRACKER_CODEX_PAYLOAD_RESULT))"

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
		-runner "$(abspath $(FIRECRACKER_CODEX_RUNNER))" \
		$(if $(strip $(FIRECRACKER_CODEX_WORKLOAD_CONTRACT)),-workload-contract "$(abspath $(FIRECRACKER_CODEX_WORKLOAD_CONTRACT))",)

runtime-firecracker-codex-control-check:
	@test -n "$(strip $(FIRECRACKER_CODEX_EVIDENCE))" || { echo "FIRECRACKER_CODEX_EVIDENCE must name the retained runtime evidence directory" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_ADAPTER_EVIDENCE))" || { echo "FIRECRACKER_CODEX_ADAPTER_EVIDENCE must name the retained adapter evidence directory" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_CONTROL_HISTORY))" || { echo "FIRECRACKER_CODEX_CONTROL_HISTORY must name the retained control History" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_HEAD_ANCHOR))" || { echo "FIRECRACKER_CODEX_HEAD_ANCHOR must name the retained external head anchor" >&2; exit 2; }
	@test -n "$(strip $(FIRECRACKER_CODEX_PAYMENT_HISTORY))" || { echo "FIRECRACKER_CODEX_PAYMENT_HISTORY must name the retained external commit history" >&2; exit 2; }
	cd runtime && go run ./cmd/check-firecracker-codex-control-evidence \
		-runtime-evidence "$(abspath $(FIRECRACKER_CODEX_EVIDENCE))" \
		-adapter-result "$(abspath $(FIRECRACKER_CODEX_ADAPTER_EVIDENCE))/result.json" \
		-history "$(abspath $(FIRECRACKER_CODEX_CONTROL_HISTORY))" \
		-head-anchor "$(abspath $(FIRECRACKER_CODEX_HEAD_ANCHOR))" \
		-payment-history "$(abspath $(FIRECRACKER_CODEX_PAYMENT_HISTORY))" \
		$(if $(strip $(FIRECRACKER_CODEX_WORKLOAD_CONTRACT)),-workload-contract "$(abspath $(FIRECRACKER_CODEX_WORKLOAD_CONTRACT))",)

# Official Claude Code in two clean, networkless Firecracker microVMs. The
# first VMM is SIGKILLed after a non-idempotent provider commit; the second VM
# reuses the host Operation result and continues without a duplicate commit.
runtime-firecracker-claude-build: runtime-firecracker-fetch runtime-claude-fetch runtime-codex-mcp-build
	@mkdir -p "$(FIRECRACKER_CLAUDE_BUILD_DIR)"
	@chmod 0700 "$(FIRECRACKER_CLAUDE_BUILD_DIR)"
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(FIRECRACKER_CLAUDE_GUEST)" ./cmd/firecracker-claude-guest
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(FIRECRACKER_CLAUDE_CELL)" ./cmd/firecracker-claude-cell
	@chmod 0500 "$(FIRECRACKER_CLAUDE_GUEST)" "$(FIRECRACKER_CLAUDE_CELL)"
	@sha256sum "$(FIRECRACKER_CLAUDE_GUEST)" "$(FIRECRACKER_CLAUDE_CELL)"

runtime-firecracker-claude-payload: runtime-claude-fetch runtime-codex-mcp-build
	@mkdir -p "$(FIRECRACKER_CLAUDE_BUILD_DIR)"
	@chmod 0700 "$(FIRECRACKER_CLAUDE_BUILD_DIR)"
	cd runtime && go run ./cmd/firecracker-claude-payload \
		-claude "$(abspath $(CLAUDE_CODE_BINARY))" \
		-claude-sha256 "$(CLAUDE_CODE_SHA256)" \
		-relay "$(abspath $(MCP_RELAY_BUNDLE_DIR))/mcp-operation-relay" \
		-output "$(abspath $(FIRECRACKER_CLAUDE_PAYLOAD))" \
		-result "$(abspath $(FIRECRACKER_CLAUDE_PAYLOAD_RESULT))"

runtime-firecracker-claude-demo: runtime-firecracker-claude-build runtime-firecracker-claude-payload
	@test -c /dev/kvm || { echo "/dev/kvm is missing or is not a character device" >&2; exit 2; }
	@test -r /dev/kvm && test -w /dev/kvm || { echo "Claude Firecracker demo requires read/write access to /dev/kvm; run through the kvm group" >&2; exit 2; }
	python3 -m adapter.firecracker_claude_mcp_runtime_demo \
		--cell-binary "$(abspath $(FIRECRACKER_CLAUDE_CELL))" \
		--guest-binary "$(abspath $(FIRECRACKER_CLAUDE_GUEST))" \
		--payload "$(abspath $(FIRECRACKER_CLAUDE_PAYLOAD))" \
		--payload-result "$(abspath $(FIRECRACKER_CLAUDE_PAYLOAD_RESULT))" \
		--claude-binary "$(abspath $(CLAUDE_CODE_BINARY))" \
		--claude-sha256 "$(CLAUDE_CODE_SHA256)" \
		--claude-lock "$(abspath $(CLAUDE_CODE_LOCK))" \
		--control-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/control" \
		--payment-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/payment" \
		--mcp-host-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/mcp-operation-host" \
		--mcp-relay-binary "$(abspath $(MCP_RELAY_BUNDLE_DIR))/mcp-operation-relay" \
		--tools-config "$(abspath runtime/deploy/mcp-operation/tools-stable.json)" \
		$(FIRECRACKER_CLAUDE_DEMO_ARGS)

runtime-firecracker-claude-check:
	@test -n "$(strip $(FIRECRACKER_CLAUDE_EVIDENCE))" || { echo "FIRECRACKER_CLAUDE_EVIDENCE must name the retained evidence directory" >&2; exit 2; }
	python3 -m adapter.check_firecracker_claude_evidence "$(abspath $(FIRECRACKER_CLAUDE_EVIDENCE))"

# Official Claude uses its ordinary Bash tool through one registered HTTP
# route into the full pinned DeathStarBench deployment. Firecracker cells have
# no NIC; complete source-VMM loss is compared with raw retry and stopping.
runtime-firecracker-deathstar-build: runtime-firecracker-claude-build
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(FIRECRACKER_CLAUDE_BUILD_DIR)/effect-proxy" ./cmd/effect-proxy
	@test -x "$(FIRECRACKER_DEATHSTAR_BASH)"
	@chmod 0500 "$(FIRECRACKER_CLAUDE_BUILD_DIR)/effect-proxy"
	@sha256sum "$(FIRECRACKER_DEATHSTAR_BASH)" "$(FIRECRACKER_CLAUDE_BUILD_DIR)/effect-proxy"

runtime-firecracker-deathstar-payload: runtime-firecracker-deathstar-build
	@mkdir -p "$(FIRECRACKER_CLAUDE_BUILD_DIR)"
	@chmod 0700 "$(FIRECRACKER_CLAUDE_BUILD_DIR)"
	cd runtime && go run ./cmd/firecracker-claude-payload \
		-claude "$(abspath $(CLAUDE_CODE_BINARY))" \
		-claude-sha256 "$(CLAUDE_CODE_SHA256)" \
		-relay "$(abspath $(MCP_RELAY_BUNDLE_DIR))/mcp-operation-relay" \
		-busybox /usr/bin/busybox \
		-bash "$(abspath $(FIRECRACKER_DEATHSTAR_BASH))" \
		-bash-library "$(abspath $(FIRECRACKER_DEATHSTAR_BASH_LIBRARY))" \
		-output "$(abspath $(FIRECRACKER_DEATHSTAR_PAYLOAD))" \
		-result "$(abspath $(FIRECRACKER_DEATHSTAR_PAYLOAD_RESULT))"

runtime-firecracker-deathstar-demo: runtime-firecracker-deathstar-build runtime-firecracker-deathstar-payload
	CELL_BINARY="$(abspath $(FIRECRACKER_CLAUDE_CELL))" \
	GUEST_BINARY="$(abspath $(FIRECRACKER_CLAUDE_GUEST))" \
	PAYLOAD="$(abspath $(FIRECRACKER_DEATHSTAR_PAYLOAD))" \
	PAYLOAD_RESULT="$(abspath $(FIRECRACKER_DEATHSTAR_PAYLOAD_RESULT))" \
	CLAUDE_BINARY="$(abspath $(CLAUDE_CODE_BINARY))" CLAUDE_SHA256="$(CLAUDE_CODE_SHA256)" \
	CONTROL_BINARY="$(abspath $(MCP_OPERATION_BUILD_DIR))/control" \
	EFFECT_PROXY_BINARY="$(abspath $(FIRECRACKER_CLAUDE_BUILD_DIR))/effect-proxy" \
	EVIDENCE_DIR="$(abspath $(FIRECRACKER_DEATHSTAR_EVIDENCE))" \
	REPETITIONS="$(FIRECRACKER_DEATHSTAR_REPETITIONS)" \
	bash runtime/deploy/firecracker-deathstar/run.sh

runtime-firecracker-deathstar-check:
	python3 -m adapter.check_firecracker_deathstar_egress_evidence \
		"$(abspath $(FIRECRACKER_DEATHSTAR_EVIDENCE))" \
		--expected-repetitions "$(FIRECRACKER_DEATHSTAR_REPETITIONS)"

# Provider-independent MCP stdio boundary. The server binary contains no
# provider target or credential; an active sandbox Unix socket supplies both.
runtime-mcp-operation-build:
	@mkdir -p "$(MCP_OPERATION_BUILD_DIR)"
	@chmod 0700 "$(MCP_OPERATION_BUILD_DIR)"
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(MCP_OPERATION_BUILD_DIR)/mcp-operation-server" ./cmd/mcp-operation-server
	@chmod 0500 "$(MCP_OPERATION_BUILD_DIR)/mcp-operation-server"
	@sha256sum "$(MCP_OPERATION_BUILD_DIR)/mcp-operation-server"

runtime-mcp-operation-check:
	cd runtime && go test -count=1 ./internal/mcpoperation ./cmd/mcp-operation-server \
		./cmd/mcp-operation-host ./cmd/mcp-operation-relay

# Real Control/History/Unix-socket/payment recovery, with no account or model.
runtime-mcp-operation-demo:
	cd runtime && go test -count=1 -v \
		-run '^TestRealHistoryMCPBoundaryRecoversLostResponseThenContinues$$' \
		./internal/mcpoperation

# Real Codex 0.147+ code-mode MCP, two App Server processes, durable MCP
# restart, query recovery, and a deliberately non-idempotent provider.
runtime-codex-mcp-build: runtime-mcp-operation-build
	@mkdir -p "$(MCP_RELAY_BUNDLE_DIR)"
	@chmod 0700 "$(MCP_RELAY_BUNDLE_DIR)"
	@test -z "$$(find "$(MCP_RELAY_BUNDLE_DIR)" -mindepth 1 -maxdepth 1 \
		! -name mcp-operation-relay -print -quit)" || { \
		echo "MCP relay bundle contains an unexpected entry" >&2; exit 2; }
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(MCP_OPERATION_BUILD_DIR)/control" ./cmd/control
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(MCP_OPERATION_BUILD_DIR)/payment" ./cmd/payment
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(MCP_OPERATION_BUILD_DIR)/mcp-operation-host" ./cmd/mcp-operation-host
	cd runtime && CGO_ENABLED=0 go build -buildvcs=false -trimpath \
		-o "$(MCP_RELAY_BUNDLE_DIR)/mcp-operation-relay" ./cmd/mcp-operation-relay
	@chmod 0500 "$(MCP_OPERATION_BUILD_DIR)/control" "$(MCP_OPERATION_BUILD_DIR)/payment" \
		"$(MCP_OPERATION_BUILD_DIR)/mcp-operation-host" "$(MCP_RELAY_BUNDLE_DIR)/mcp-operation-relay"
	@sha256sum "$(MCP_OPERATION_BUILD_DIR)/control" "$(MCP_OPERATION_BUILD_DIR)/payment" \
		"$(MCP_OPERATION_BUILD_DIR)/mcp-operation-host" "$(MCP_RELAY_BUNDLE_DIR)/mcp-operation-relay"

runtime-codex-mcp-demo: runtime-codex-mcp-build
	python3 -m adapter.codex_mcp_runtime_demo \
		--control-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/control" \
		--payment-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/payment" \
		--mcp-host-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/mcp-operation-host" \
		--mcp-relay-binary "$(abspath $(MCP_RELAY_BUNDLE_DIR))/mcp-operation-relay" \
		$(CODEX_MCP_DEMO_ARGS)

runtime-codex-mcp-docker-demo: runtime-codex-mcp-build runtime-image
	python3 -m adapter.codex_mcp_runtime_demo \
		--control-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/control" \
		--payment-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/payment" \
		--mcp-host-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/mcp-operation-host" \
		--mcp-relay-binary "$(abspath $(MCP_RELAY_BUNDLE_DIR))/mcp-operation-relay" \
		--docker-image "$(RUNTIME_IMAGE)" \
		$(CODEX_MCP_DOCKER_ARGS)

runtime-codex-mcp-check:
	@test -n "$(strip $(CODEX_MCP_EVIDENCE))" || { echo "CODEX_MCP_EVIDENCE must name the retained evidence directory" >&2; exit 2; }
	python3 -m adapter.check_codex_mcp_evidence "$(abspath $(CODEX_MCP_EVIDENCE))"

# Pinned official Claude Code release. The fetcher verifies Anthropic's release
# key fingerprint, detached manifest signature, manifest entry, size, and hash.
runtime-claude-source-check:
	@for claude_input in $(CLAUDE_CODE_FETCH_INPUTS); do \
		test -f "$$claude_input" && test ! -L "$$claude_input" || { \
			echo "$$claude_input must be a direct regular file" >&2; exit 2; \
		}; \
		expected_hash="$$(git rev-parse --verify "HEAD:$$claude_input" 2>/dev/null)" || { \
			echo "$$claude_input must be committed before the Claude fetcher can run" >&2; exit 2; \
		}; \
		actual_hash="$$(git hash-object --no-filters "$$claude_input")" || exit 2; \
		test "$$actual_hash" = "$$expected_hash" || { \
			echo "$$claude_input bytes do not match HEAD" >&2; exit 2; \
		}; \
	done
	@test -z "$$(git status --porcelain=v1 --untracked-files=all -- $(CLAUDE_CODE_FETCH_INPUTS))" || { \
		echo "Claude fetch inputs must match HEAD before execution" >&2; \
		git status --short -- $(CLAUDE_CODE_FETCH_INPUTS) >&2; exit 2; \
	}

runtime-claude-fetch: runtime-claude-source-check
	bash runtime/deploy/claude-code/fetch-assets.sh

# Real Claude Code 2.1.233, two clean process lifetimes, one durable MCP host,
# and a non-idempotent provider held after its first commit.
runtime-claude-mcp-demo: runtime-claude-fetch runtime-codex-mcp-build
	python3 -m adapter.claude_mcp_runtime_demo \
		--claude-binary "$(abspath $(CLAUDE_CODE_BINARY))" \
		--claude-sha256 "$(CLAUDE_CODE_SHA256)" \
		--claude-lock "$(abspath $(CLAUDE_CODE_LOCK))" \
		--control-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/control" \
		--payment-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/payment" \
		--mcp-host-binary "$(abspath $(MCP_OPERATION_BUILD_DIR))/mcp-operation-host" \
		--mcp-relay-binary "$(abspath $(MCP_RELAY_BUNDLE_DIR))/mcp-operation-relay" \
		--tools-config "$(abspath runtime/deploy/mcp-operation/tools-stable.json)" \
		$(CLAUDE_MCP_DEMO_ARGS)

runtime-claude-mcp-check:
	@test -n "$(strip $(CLAUDE_MCP_EVIDENCE))" || { echo "CLAUDE_MCP_EVIDENCE must name the retained evidence directory" >&2; exit 2; }
	python3 -m adapter.check_claude_mcp_evidence "$(abspath $(CLAUDE_MCP_EVIDENCE))"

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
		adapter.test_app_server.DeterministicResponsesServerTests \
		adapter.test_app_server.CodexAppServerModeTests \
		adapter.test_docker_codex \
		adapter.test_firecracker_codex \
		adapter.test_firecracker_codex_runtime_demo \
		adapter.test_mock_anthropic \
		adapter.test_check_claude_mcp_evidence \
		adapter.test_check_firecracker_claude_evidence \
		adapter.test_codex_isolated_runtime_demo \
		adapter.test_check_codex_isolated_evidence \
		adapter.test_codex_integrated_runtime_demo \
		adapter.test_check_codex_integrated_evidence \
		adapter.test_check_deathstar_evidence
	$(MAKE) runtime-codex-isolated-check
	$(MAKE) runtime-integrated-check
	$(MAKE) runtime-deathstar-check
