#!/usr/bin/env bash
# One command: fetch deps, start the stack, install every addon in dependency
# order, run the tests, write a report.
#
#   ./ops/run_odoo_tests.sh                 # full run on a fresh database
#   ./ops/run_odoo_tests.sh --keep-db       # reuse the existing database
#   ./ops/run_odoo_tests.sh --tests-only    # re-run tests, skip the install
#   ./ops/run_odoo_tests.sh --addon hrms_fnf
#
# Exits non-zero if the install fails, if any test fails, or if the statutory
# sign-off gate is not holding. That last one is deliberate: a run that installs
# cleanly and leaves a usable statutory rate behind is a failed run, because it
# means an unconfigured database looks go-live ready.
#
# Nothing here runs on the development host that authored this code; that host has
# no Docker. This script is for the laptop.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Options ────────────────────────────────────────────────────────────────
KEEP_DB=0
TESTS_ONLY=0
ADDONS_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --keep-db)    KEEP_DB=1; shift ;;
    --tests-only) TESTS_ONLY=1; KEEP_DB=1; shift ;;
    --addon)      ADDONS_ARG="$ADDONS_ARG ${2:-}"; shift 2 ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# Load .env if present, else fall back to the example's placeholders so the
# script is runnable on a fresh clone without a setup step.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
: "${ODOO_VERSION:=18.0}"
: "${POSTGRESQL_VERSION:=16}"
: "${ODOO_DB:=hrpay}"
: "${ODOO_DB_USER:=odoo}"
: "${ODOO_DB_PASSWORD:=odoo}"
: "${ODOO_ADMIN_PASSWORD:=admin}"
: "${COMPOSE:=docker compose}"

# Dependency order. Odoo resolves the graph itself, but passing them in order
# makes the install log readable and keeps the first error meaningful rather
# than being whichever module happened to sort first.
ADDONS_DEFAULT="hrms_core_ext hrms_statutory hrms_roster hrms_fnf hrms_helpdesk hrms_payroll_run"
ADDONS="${ADDONS_ARG:-$ADDONS_DEFAULT}"
ADDONS_CSV="$(echo "$ADDONS" | tr ' ' ',' | sed 's/^,//;s/,$//')"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="docs/test-runs"
REPORT="$REPORT_DIR/$RUN_ID.md"
LOG="$REPORT_DIR/$RUN_ID.log"

mkdir -p "$REPORT_DIR"

# Defined before first use: the install path renders a report too, so that a
# failed install still leaves an artefact.
_render_report() {
  local status="$1" exit_code="$2" total_tests="$3" total_failures="$4"
  python3 ops/render_report.py \
    --template docs/test-run-report-template.md \
    --output "$REPORT" \
    --log "$(basename "$LOG")" \
    --status "$status" \
    --run-id "$RUN_ID" \
    --addons "$ADDONS_CSV" \
    --db "$ODOO_DB" \
    --odoo-version "$ODOO_VERSION" \
    --pg-version "$POSTGRESQL_VERSION" \
    --total-tests "$total_tests" \
    --total-failures "$total_failures" \
    --exit-code "$exit_code" \
    --summary "${tests_line:-}"
  # Revision and branch are derived by render_report.py rather than passed in, so
  # there is one source of truth for which code the report describes.
}

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; }

# ── Preflight ──────────────────────────────────────────────────────────────
say "Preflight"
command -v docker >/dev/null || { fail "docker not found. Install Docker and retry."; exit 1; }
$COMPOSE version >/dev/null 2>&1 || { fail "'$COMPOSE version' failed."; exit 1; }
echo "  docker:  $(docker --version)"
echo "  compose: $($COMPOSE version --short 2>/dev/null || echo unknown)"
echo "  odoo:    $ODOO_VERSION (CE)"
echo "  pg:      $POSTGRESQL_VERSION"
echo "  db:      $ODOO_DB"
echo "  addons:  $ADDONS_CSV"

# ── Dependencies ───────────────────────────────────────────────────────────
say "Community dependencies"
bash ops/fetch_deps.sh .oca || {
  fail "dependency fetch failed. Without OCA payroll modules the statutory, F&F"
  fail "and payroll-run addons cannot install."
  exit 1
}

# ── Start the stack ────────────────────────────────────────────────────────
say "Starting the stack"
if [ "$KEEP_DB" -eq 0 ]; then
  echo "  dropping database volume for a clean run"
  $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true
fi
$COMPOSE up -d --wait postgres || {
  fail "postgres did not become healthy."
  $COMPOSE logs --tail=50 postgres >&2 || true
  exit 1
}
echo "  postgres healthy"

# ── Database ───────────────────────────────────────────────────────────────
if [ "$KEEP_DB" -eq 0 ]; then
  say "Creating database"
  # Odoo creates the database itself on -i when the user can; using its own path
  # avoids a mismatch between createdb and Odoo's expectations.
  echo "  (Odoo creates '$ODOO_DB' during the install step)"
fi

# ── Install ────────────────────────────────────────────────────────────────
if [ "$TESTS_ONLY" -eq 0 ]; then
  say "Installing addons in dependency order"
  echo "  log: $LOG"
  set +e
  $COMPOSE run --rm -T odoo \
    odoo \
      -d "$ODOO_DB" \
      -i "$ADDONS_CSV" \
      --stop-after-init \
      --without-demo=all \
      --log-level="${ODOO_LOG_LEVEL:-info}" \
      --max-cron-threads=0 \
      > "$LOG" 2>&1
  install_rc=$?
  set -e
  if [ "$install_rc" -ne 0 ]; then
    fail "install failed (exit $install_rc). Tail of $LOG:"
    tail -60 "$LOG" >&2
    _render_report "install-failed" "$install_rc" 0 0 || true
    exit "$install_rc"
  fi
  echo "  install ok"
fi

# ── Tests ──────────────────────────────────────────────────────────────────
say "Running tests"
test_log="$LOG"
set +e
$COMPOSE run --rm -T odoo \
  odoo \
    -d "$ODOO_DB" \
    -u "$ADDONS_CSV" \
    --stop-after-init \
    --test-enable \
    --log-level="${ODOO_LOG_LEVEL:-test}" \
    --max-cron-threads=0 \
    >> "$test_log" 2>&1
test_rc=$?
set -e

# Parse Odoo's own summary lines rather than trusting the exit code alone: a
# crash after the last test reports a non-zero exit with no failures listed.
tests_line="$(grep -oE '[0-9]+ tests? [0-9]+ failures?[^,]*' "$test_log" | tail -1 || true)"
failures_line="$(grep -oE '[0-9]+ failures? [0-9]+ errors?' "$test_log" | tail -1 || true)"
total_tests="$(echo "$tests_line" | grep -oE '^[0-9]+' || echo 0)"
total_failures="$(echo "$failures_line" | grep -oE '^[0-9]+' || echo 0)"

echo "  summary: ${tests_line:-<none found in log>}"

# ── Statutory gate check ───────────────────────────────────────────────────
say "Verifying the statutory sign-off gate is still holding"
gate_out="$($COMPOSE run --rm -T odoo odoo shell -d "$ODOO_DB" --no-http <"$REPO_ROOT/ops/check_statutory_gate.py" 2>&1 || true)"
echo "$gate_out" | tail -5
if echo "$gate_out" | grep -q 'GATE_HOLDING'; then
  gate_ok=1
  echo "  sign-off gate holding: no statutory code resolves to a usable value"
else
  gate_ok=0
  fail "sign-off gate check did not confirm. See output above."
fi

# ── Report ─────────────────────────────────────────────────────────────────
_render_report "$([ "$test_rc" -eq 0 ] && [ "$gate_ok" -eq 1 ] && echo pass || echo fail)" \
  "$test_rc" "${total_tests:-0}" "${total_failures:-0}" || true

say "Report"
echo "  $REPORT"
echo "  $test_log"

if [ "$test_rc" -ne 0 ]; then
  fail "test run failed (exit $test_rc). Tail of $test_log:"
  tail -60 "$test_log" >&2
  exit "$test_rc"
fi
if [ "$gate_ok" -ne 1 ]; then
  fail "run completed but the statutory sign-off gate could not be confirmed."
  exit 1
fi

echo
echo "All addon tests passed and the statutory sign-off gate is holding."