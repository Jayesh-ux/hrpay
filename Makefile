# Makefile — hrpay platform
# Every target is safe to re-run. Destructive targets require CONFIRM=yes.

SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE ?= docker compose
ENV_FILE ?= .env
ADDONS_DIR := $(PWD)/addons
OCA_DIR ?= $(PWD)/.oca

# Never destroy data without explicit consent.
define require_confirm
	@if [ "$(CONFIRM)" != "yes" ]; then \
		echo "REFUSING: destructive target requires CONFIRM=yes"; exit 1; \
	fi
endef

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-24s\033[0m %s\n",$$1,$$2}'

# ─── Setup ───────────────────────────────────────────────────────────────────

.PHONY: env
env: ## Create .env from example (interactive; never overwrite)
	@if [ -f $(ENV_FILE) ]; then echo "$(ENV_FILE) exists; not overwriting"; \
	 else cp .env.example $(ENV_FILE); \
	      chmod 600 $(ENV_FILE); echo "Created $(ENV_FILE) — EDIT IT before running."; fi

.PHONY: oca
oca: ## Fetch pinned OCA dependency modules into $(OCA_DIR)
	@mkdir -p $(OCA_DIR)
	@bash ops/fetch_deps.sh $(OCA_DIR)

# `pin` deliberately does not generate versions/lock.txt. A lock that the build
# rewrites is not a lock: fetching a moving branch and recording whatever it
# returned is exactly the drift the lock exists to prevent, and it would let a
# dependency change enter a commit unreviewed. To move a pin, edit the file by
# hand, run `make oca` to prove the new revision resolves, and review the diff.
.PHONY: pin
pin: ## Verify every pinned revision resolves, then show the module inventory
	@bash ops/fetch_deps.sh $(OCA_DIR)
	@echo
	@echo "Pinned revisions verified. versions/lock.txt was NOT modified."
	@echo "To move a pin, edit versions/lock.txt yourself and re-run this target."
	@cat $(OCA_DIR)/*.modules

.PHONY: up
up: env ## Start the dev stack (Odoo + PostgreSQL)
	$(COMPOSE) --env-file $(ENV_FILE) up -d --wait
	@echo "Odoo  → http://localhost:8069"
	@echo "Postgres → localhost:5432"

.PHONY: down
down: ## Stop the dev stack (keeps volumes)
	$(COMPOSE) --env-file $(ENV_FILE) down

.PHONY: nuke
nuke: require_confirm ## DESTROY: stop stack and DELETE ALL DATA VOLUMES
	$(COMPOSE) --env-file $(ENV_FILE) down -v
	@echo "All volumes deleted."

.PHONY: logs
logs: ## Tail logs
	$(COMPOSE) --env-file $(ENV_FILE) logs -f --tail=100

.PHONY: ps
ps: ## Service status
	$(COMPOSE) --env-file $(ENV_FILE) ps

# ─── Database ────────────────────────────────────────────────────────────────

.PHONY: odoo-shell
odoo-shell: ## Odoo python shell
	$(COMPOSE) --env-file $(ENV_FILE) exec odoo odoo shell -d $${ODOO_DB:-hrpay}

.PHONY: psql
psql: ## PostgreSQL shell
	$(COMPOSE) --env-file $(ENV_FILE) exec postgres psql -U $${POSTGRES_USER:-odoo} -d $${ODOO_DB:-hrpay}

.PHONY: restore
restore: require_confirm ## DESTROY: drop and recreate the Odoo database from a dump
	@test -n "$(FILE)" || { echo "Usage: make restore FILE=dump.sql.gz CONFIRM=yes"; exit 1; }
	$(COMPOSE) --env-file $(ENV_FILE) exec -T postgres psql -U $${POSTGRES_USER:-odoo} -c "DROP DATABASE IF EXISTS $${ODOO_DB:-hrpay};"
	$(COMPOSE) --env-file $(ENV_FILE) exec -T postgres psql -U $${POSTGRES_USER:-odoo} -c "CREATE DATABASE $${ODOO_DB:-hrpay} OWNER $${POSTGRES_USER:-odoo};"
	gzip -dc $(FILE) | $(COMPOSE) --env-file $(ENV_FILE) exec -T postgres psql -U $${POSTGRES_USER:-odoo} -d $${ODOO_DB:-hrpay}

# ─── Odoo modules ────────────────────────────────────────────────────────────

.PHONY: install-addons
install-addons: ## Install our addons into the Odoo database
	$(COMPOSE) --env-file $(ENV_FILE) exec odoo \
	  odoo -d $${ODOO_DB:-hrpay} \
	  -i hrms_core_ext,hrms_statutory,hrms_roster,hrms_fnf,hrms_helpdesk,hrms_payroll_run \
	  --stop-after-init --without-demo=all

.PHONY: update-addons
update-addons: ## Upgrade our addons
	$(COMPOSE) --env-file $(ENV_FILE) exec odoo \
	  odoo -d $${ODOO_DB:-hrpay} \
	  -u hrms_core_ext,hrms_statutory,hrms_roster,hrms_fnf,hrms_helpdesk,hrms_payroll_run \
	  --stop-after-init

# ─── Tests ───────────────────────────────────────────────────────────────────
# Run on the development laptop, not in this container.

.PHONY: test-odoo
test-odoo: ## One command: install all addons in order, run tests, write a report
	./ops/run_odoo_tests.sh

.PHONY: test-standalone
test-standalone: ## Run the Odoo-free tests (solver + TDS arithmetic); no stack needed
	python3 tests/standalone/test_solver_constraints.py
	python3 tests/standalone/test_tds_arithmetic_DEV.py

# The integration, AI and standalone roster-solver services are Phase 3/4 and are
# not built yet. The roster solver that exists is inside hrms_roster and is
# covered by test-standalone and by the Odoo suite.
.PHONY: test-services
test-services:
	@echo "services/ is not implemented yet (Phase 3/4). Nothing to run."
	@exit 1

.PHONY: test-e2e
test-e2e:
	@echo "ops/run_e2e.sh is not written yet. Blocking for Gate 1A."
	@exit 1

.PHONY: test-load
test-load:
	@echo "ops/run_load_test.sh is not written yet. Blocking for Gate 1A."
	@exit 1

.PHONY: golden
golden: ## Regenerate F&F golden files (requires explicit justification)
	@echo "Golden files are reviewed artefacts. Regeneration requires:"
	@echo "  1. A payroll specialist has signed off the new expected values."
	@echo "  2. The statutory config register rows used are marked validated."
	@echo "  3. You have diffed the change and accept it."
	@read -p "Type REGENERATE to proceed: " c; [ "$$c" = "REGENERATE" ] || exit 1
	@echo "ops/regenerate_golden.sh is not written yet; golden files are not in the repo."
	@exit 1

# ─── Quality ─────────────────────────────────────────────────────────────────

.PHONY: check-static
check-static: ## Cross-reference addons and views without an Odoo instance
	python3 tools/check_addons.py
	python3 tools/check_views.py

.PHONY: lint
lint: ## Lint everything
	ruff check services/ ops/
	pre-commit run --all-files
	$(MAKE) check-static

.PHONY: typecheck
typecheck: ## Static type check services
	mypy services/

.PHONY: fmt
fmt: ## Auto-format
	ruff format services/ ops/
	ruff check --fix services/ ops/

.PHONY: scan
scan: ## Dependency + secret + SAST scans
	@echo "ops/security_scan.sh is not written yet (dependency/secret/SAST scanning)."
	@echo "Refusing to report success for work that did not run."
	@exit 1

.PHONY: zap
zap: ## OWASP ZAP baseline scan (needs a running stack)
	@echo "ops/zap_scan.sh is not written yet (the OWASP ZAP baseline scan)."
	@echo "Refusing to report success for work that did not run."
	@exit 1

# ─── Compliance ──────────────────────────────────────────────────────────────

.PHONY: compliance-report
compliance-report: ## List statutory config rows still awaiting sign-off
	@echo "ops/compliance_report.py is not written yet (the statutory sign-off report)."
	@echo "Refusing to report success for work that did not run."
	@exit 1

.PHONY: compliance-block
compliance-block: ## Fail if any rule would go live without professional sign-off
	@echo "ops/compliance_report.py is not written yet (the statutory sign-off report)."
	@echo "Interim gate: ops/check_statutory_gate.py, run by ops/run_odoo_tests.sh."
	@echo "Refusing to report success for work that did not run."
	@exit 1

# ─── Deploy ──────────────────────────────────────────────────────────────────

.PHONY: k8s-build
k8s-build: ## Build and push container images
	@echo "ops/build_images.sh is not written yet (container image builds)."
	@echo "Refusing to report success for work that did not run."
	@exit 1

.PHONY: k8s-apply
k8s-apply: ## Apply to the current kubectl context
	@read -p "Cluster: $(KUBE_CONTEXT). Type the name to confirm: " c; \
	 test "$$c" = "$(KUBE_CONTEXT)" || { echo "aborted"; exit 1; }
	kubectl --context $(KUBE_CONTEXT) apply -f deploy/k8s/

.PHONY: dr-drill
dr-drill: ## Disaster-recovery drill (restores backup into an isolated namespace)
	@echo "ops/dr_drill.sh is not written yet (the disaster-recovery drill)."
	@echo "Refusing to report success for work that did not run."
	@exit 1

.PHONY: backup
backup: ## Back up all databases
	@bash ops/backup.sh