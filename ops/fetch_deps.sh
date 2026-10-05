#!/usr/bin/env bash
# Fetch the pinned community (OCA) dependency modules.
#
# Everything here is LGPL/AGPL community code. If a fetch would pull Odoo
# Enterprise, that is a hard failure, not a warning: the project prohibits
# Enterprise code outright (versions/pinned.env ODOO_EE_ABSENT).
#
# Repositories are checked out at the 18.0 branch, which is what
# versions/pinned.env records as verified.

set -euo pipefail

OCA_DIR="${1:-${OCA_DIR:-.oca}}"
ODOO_SERIES="${ODOO_SERIES:-18.0}"

# repo url | ref | modules we expect to find underneath
REPOS=(
  "https://github.com/OCA/payroll|18.0|hr_payroll_community hr_payroll_account_community"
  "https://github.com/OCA/helpdesk|18.0|helpdesk_mgmt helpdesk_mgmt_sla helpdesk_mgmt_type helpdesk_mgmt_rating helpdesk_mgmt_team"
)

mkdir -p "$OCA_DIR"

failed=0
for spec in "${REPOS[@]}"; do
  IFS='|' read -r url ref modules <<<"$spec"
  name="$(basename "$url")"
  dest="$OCA_DIR/$name"

  if [ -d "$dest/.git" ]; then
    echo "==> $name already present; updating to $ref"
    git -C "$dest" fetch --quiet origin "$ref" || { echo "  fetch failed for $name"; failed=1; continue; }
    git -C "$dest" checkout --quiet "$ref"
  else
    echo "==> cloning $name at $ref"
    # --depth 1 with a branch keeps the checkout small; the pinned SHA is
    # recorded by ops/resolve_lock.sh when a full history is wanted.
    if ! git clone --quiet --depth 1 --branch "$ref" "$url" "$dest"; then
      echo "  clone failed for $name ($url @ $ref)"
      failed=1
      continue
    fi
  fi

  sha="$(git -C "$dest" rev-parse HEAD)"
  echo "  $name -> $sha"
  git -C "$dest" rev-parse HEAD > "$OCA_DIR/$name.sha"

  # Verify the modules we depend on are actually present. Cloning successfully is
  # not evidence the module names are right, and a rename upstream would otherwise
  # surface as an obscure install failure.
  missing=""
  for module in $modules; do
    if [ ! -d "$dest/$module" ]; then
      missing="$missing $module"
    fi
  done
  if [ -n "$missing" ]; then
    echo "  WARNING: $name is missing:$missing"
    echo "  These are referenced by our manifests. Check for a rename upstream"
    echo "  before assuming the install will work."
    failed=1
  fi
done

# ── Refuse to proceed if Enterprise code is present ────────────────────────
ee_found="$(find "$OCA_DIR" -maxdepth 2 -type d \
  \( -name hr_payroll -o -name account_accountant -o -name l10n_in_hr_payroll \
     -o -name planning -o -name studio \) -print 2>/dev/null || true)"
if [ -n "$ee_found" ]; then
  echo
  echo "ERROR: Odoo Enterprise modules present in $OCA_DIR:"
  echo "$ee_found" | sed 's/^/  /'
  echo "The project prohibits Enterprise code. Stop and review."
  exit 1
fi

if [ "$failed" -ne 0 ]; then
  echo
  echo "One or more repositories did not resolve cleanly. See warnings above."
  exit 1
fi

echo
echo "Dependencies ready in $OCA_DIR."