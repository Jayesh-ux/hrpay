#!/usr/bin/env bash
# Entrypoint wrapper for the odoo service.
#
# Why not just use the image's own entrypoint: the core addons path differs
# between Odoo releases and between install methods (apt vs pip), and getting it
# wrong produces "module not found" for hr.payslip or account.move that looks
# like a missing dependency in our own manifests. So we ask the installed Python
# package where its addons live instead of assuming.
#
# Deriving the path is the whole reason this file exists. Everything else is a
# thin wrapper around `odoo`.

set -euo pipefail

HRPAY_ADDONS="${HRPAY_ADDONS:-/opt/hrpay/addons}"
HRPAY_OCA_ADDONS="${HRPAY_OCA_ADDONS:-/opt/hrpay/oca}"

log() { printf '[entrypoint] %s\n' "$*" >&2; }

# ── Resolve the core addons directory ──────────────────────────────────────
core_addons=""
if odoo_bin="$(command -v odoo || command -v odoo-bin || true)"; then
  core_addons="$(python3 - "$odoo_bin" <<'PY' || true
import os
import sys

# Prefer the console script's own package location; fall back to importable.
candidates = []
exe = sys.argv[1]
if exe:
    real = os.path.realpath(exe)
    # /usr/lib/python3/dist-packages/odoo-bin -> .../odoo/addons
    root = os.path.dirname(real)
    for depth in ("", "..", "../.."):
        candidates.append(os.path.normpath(os.path.join(root, depth, "odoo", "addons")))

try:
    import odoo  # noqa: PLC0415
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(odoo.__file__)), "addons"))
except Exception:
    pass

for candidate in candidates:
    if candidate and os.path.isdir(candidate):
        print(candidate)
        break
PY
)"
fi

if [ -z "$core_addons" ]; then
  log "FATAL: could not locate the Odoo core addons directory."
  log "  Looked via: ${odoo_bin:-<odoo not found on PATH>}"
  log "  This usually means the image is not an Odoo image, or Odoo is installed"
  log "  somewhere unexpected. Run 'odoo --version' inside the container."
  exit 1
fi

# ── Assemble the addons path ───────────────────────────────────────────────
addons_path="$core_addons"
[ -d "$HRPAY_ADDONS" ] && addons_path="$addons_path,$HRPAY_ADDONS"
[ -d "$HRPAY_OCA_ADDONS" ] && addons_path="$addons_path,$HRPAY_OCA_ADDONS"

log "core addons:    $core_addons"
log "our addons:     $HRPAY_ADDONS"
[ -d "$HRPAY_OCA_ADDONS" ] && log "oca addons:     $HRPAY_OCA_ADDONS"
log "addons path:    $addons_path"

# ── Warn about missing community dependencies, loudly but not fatally ──────
# hrms_statutory, hrms_fnf and hrms_payroll_run all depend on the OCA payroll
# modules. A fresh clone without `make oca` will fail at install time with a
# message about a module that is genuinely not optional, so say so now.
for module in hr_payroll_community hr_payroll_account_community; do
  if ! find "$HRPAY_OCA_ADDONS" -maxdepth 3 -type d -name "$module" -print -quit 2>/dev/null | grep -q .; then
    log "WARNING: OCA module '$module' not found under $HRPAY_OCA_ADDONS."
    log "         Run 'make oca' (or ops/fetch_deps.sh) before installing addons."
  fi
done

cd "${ODOO_DATA_DIR:-/var/lib/odoo}" 2>/dev/null || cd /opt/hrpay
exec "$@" --addons-path="$addons_path"