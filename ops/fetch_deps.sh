#!/usr/bin/env bash
# Fetch the pinned community (OCA / Open HRMS) dependency modules.
#
# Everything here is LGPL or AGPL community code. If a fetch would pull Odoo
# Enterprise, that is a hard failure, not a warning: the project prohibits
# Enterprise code outright (versions/pinned.env ODOO_EE_ABSENT, ADR-0002).
#
# Repositories are checked out at the exact commit recorded in versions/lock.txt,
# NOT at the branch head. A branch is not a version: `18.0` moves, so the same
# code would produce different payroll numbers on different days and an upstream
# commit would be indistinguishable from our own bug.
#
# To move a pin deliberately, edit versions/lock.txt and re-run. Never re-pin as
# a side effect of a failing build -- that is how a dependency regression gets
# committed instead of diagnosed.

set -euo pipefail

OCA_DIR="${1:-${OCA_DIR:-.oca}}"
LOCK_FILE="${LOCK_FILE:-versions/lock.txt}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# An absolute LOCK_FILE is honoured as-is; a relative one resolves against the
# repository root so the script can be run from any working directory.
case "$LOCK_FILE" in
  /*) LOCK="$LOCK_FILE" ;;
  *) LOCK="$REPO_ROOT/$LOCK_FILE" ;;
esac

if [ ! -f "$LOCK" ]; then
  echo "ERROR: $LOCK_FILE not found."
  echo "Dependencies are pinned by exact commit; without the lock file there is"
  echo "nothing to pin to and this script would silently fetch a branch head."
  exit 1
fi

failed=0

# ── Refuse to proceed if Enterprise code is already present ───────────────────
# Checked before fetching, not only after, so a contaminated .oca from an earlier
# run is caught even if this run's checkouts are clean.
refuse_enterprise() {
  local where="$1"
  local found
  found="$(find "$where" -maxdepth 3 -type d \
    \( -name 'ent_*' -o -name 'hr_payroll' -o -name 'hr_appraisal' \
       -o -name 'account_accountant' -o -name 'l10n_in_hr_payroll' \
       -o -name 'planning' -o -name 'studio' -o -name 'documents' \
       -o -name 'knowledge' -o -name 'sign' \) -print 2>/dev/null || true)"
  if [ -n "$found" ]; then
    echo
    echo "ERROR: Odoo Enterprise modules present in $where:"
    echo "$found" | sed 's/^/  /'
    echo
    echo "The project prohibits Enterprise code (OPL-1). Stop and review."
    echo "If these came from a stale checkout, delete $OCA_DIR and re-run."
    exit 1
  fi
}

mkdir -p "$OCA_DIR"
refuse_enterprise "$OCA_DIR"

# Clear the recorded module manifests from any previous run, so a module that is
# no longer depended on does not linger in the record looking current.
rm -f "$OCA_DIR"/*.modules 2>/dev/null || true

# ── Fetch each locked repository ──────────────────────────────────────────────
#
# Sparse checkout is what keeps this script honest. OpenHRMS ships
# `ent_uae_wps_report` (Odoo Enterprise, OPL-1) on the same 18.0 branch as the
# LGPL payroll modules, so a full clone would drag Enterprise code onto the disk
# and then fail its own policy check. Restricting the working tree to exactly the
# locked module directories means an Enterprise module is never fetched at all,
# rather than fetched and merely ignored.
fetched=0

trim() {
  local s="$1"
  # Strip leading and trailing whitespace without invoking a subprocess, so this
  # works where /dev/fd is unavailable (see the redirect at the bottom of the
  # loop, which deliberately avoids process substitution for the same reason).
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

# Read the lock from a plain file redirect rather than `< <(...)`. Process
# substitution depends on /dev/fd, which is not present in every container and
# minimal image; when it is missing the loop reads nothing and the script either
# silently fetches nothing or dies confusingly.
while IFS='|' read -r repo ref sha modules || [ -n "${repo:-}" ]; do
  case "$repo" in
    ''|\#*) continue ;;                      # blank or comment line
  esac
  repo="$(trim "$repo")"
  ref="$(trim "$ref")"
  sha="$(trim "$sha")"
  modules="$(trim "$modules")"
  [ -z "$repo" ] && continue

  name="$(basename "$repo")"
  dest="$OCA_DIR/$name"

  # The lock records `owner/name`, which git cannot clone directly.
  case "$repo" in
    http://*|https://*|git@*|ssh://*|file://*|/tmp/*) url="$repo" ;;
    */*) url="https://github.com/$repo" ;;
    *)
      echo "ERROR: cannot interpret repository '$repo' in $LOCK_FILE"
      echo "  Expected 'owner/name' or a full URL."
      failed=1
      continue
      ;;
  esac

  # The locked module directory names, which are also the sparse-checkout set.
  module_dirs=""
  for entry in $(echo "$modules" | tr ',' ' '); do
    module_dirs="$module_dirs ${entry%%=*}"
  done

  if [ ! -d "$dest/.git" ]; then
    echo "==> cloning $name ($ref, sparse: $module_dirs)"
    # --filter=blob:none keeps the tree metadata without downloading file
    # contents, and --no-checkout means the full branch is never written to disk.
    # The locked SHA is fetched afterwards; a shallow clone of the branch head
    # would not contain an older pinned commit.
    if ! git clone --quiet --filter=blob:none --no-checkout --branch "$ref" \
         "$url" "$dest" 2>/dev/null; then
      echo "  ERROR: clone failed for $name ($url @ $ref)"
      failed=1
      continue
    fi
    git -C "$dest" sparse-checkout init --cone >/dev/null
    # shellcheck disable=SC2086 # module_dirs is an intentional word list
    git -C "$dest" sparse-checkout set $module_dirs >/dev/null
  else
    echo "==> $name already present; verifying against the lock"
    # Re-apply the sparse set so a checkout made before this was enforced, or by
    # hand, cannot smuggle an extra module onto the addons path.
    git -C "$dest" sparse-checkout set $module_dirs >/dev/null 2>&1 || true
  fi

  # ── Pin to the locked commit ────────────────────────────────────────────────
  if ! git -C "$dest" cat-file -e "$sha^{commit}" 2>/dev/null; then
    # The pinned commit is not in this clone. Fetch it by SHA; GitHub allows
    # fetching arbitrary reachable objects. If that fails the pin is unreachable
    # or rewritten upstream, and guessing a nearby commit is the one thing this
    # script must not do.
    if ! git -C "$dest" fetch --quiet origin "$sha" 2>/dev/null; then
      echo "  ERROR: locked commit $sha is not reachable from $url"
      echo "    The lock file may be stale, or the commit may have been rewritten."
      failed=1
      continue
    fi
  fi
  if ! git -C "$dest" checkout --quiet "$sha" 2>/dev/null; then
    echo "  ERROR: could not check out $sha in $name"
    failed=1
    continue
  fi

  # Re-read HEAD after checkout. If it does not match the lock we did not get
  # what we asked for, and continuing would mean testing against an unknown tree.
  actual="$(git -C "$dest" rev-parse HEAD)"
  if [ "$actual" != "$sha" ]; then
    echo "  ERROR: $name is at $actual after checkout, lock requires $sha"
    failed=1
    continue
  fi
  echo "  $name -> $actual (locked)"

  # ── Verify every module we depend on exists, and record its licence ─────────
  # Cloning successfully is not evidence the module names are right, and a rename
  # upstream would otherwise surface as an obscure install failure.
  for entry in $(echo "$modules" | tr ',' ' '); do
    module="${entry%%=*}"
    expected="${entry#*=}"
    expect_version="${expected%%:*}"
    expect_license="${expected#*:}"

    if [ ! -d "$dest/$module" ]; then
      echo "  ERROR: $name is missing module '$module'"
      echo "    Check for a rename upstream before assuming the install will work."
      failed=1
      continue
    fi
    manifest="$dest/$module/__manifest__.py"
    if [ ! -f "$manifest" ]; then
      echo "  ERROR: $module has no __manifest__.py"
      failed=1
      continue
    fi
    # Read the version and licence from the manifest. Parsed rather than grepped
    # because Odoo manifests are Python dicts and a textual match picks up the
    # version string inside a comment or a README field.
    parsed="$(python3 - "$manifest" <<'PY' 2>/dev/null || true
import ast, sys
raw = open(sys.argv[1]).read()
data = ast.literal_eval(raw[raw.index("{"):])
print(f"{data.get('version', '?')}|{data.get('license', '?')}")
PY
)"
    found_version="${parsed%%|*}"
    found_license="${parsed#*|}"

    # A version or licence we cannot read is not a warning. It means the manifest
    # changed shape, and carrying on would record a module as approved on the
    # strength of a value nobody actually checked.
    if [ "$found_version" = "?" ] || [ "$found_license" = "?" ]; then
      echo "  ERROR: could not read version/licence from $module's __manifest__.py"
      echo "    Upstream may have changed the manifest format. Review before trusting it."
      failed=1
      continue
    fi

    # Upstream moved, or we recorded the wrong revision. Either way the addons
    # path no longer matches what was reviewed, so this is a stop rather than a
    # warning: a silent version drift is how a statutory regression gets in.
    if [ "$found_version" != "$expect_version" ]; then
      echo "  ERROR: $module is $found_version but the lock says $expect_version"
      echo "    Upstream moved. Review the diff, then update versions/lock.txt."
      failed=1
    fi
    if [ "$found_license" != "$expect_license" ]; then
      echo "  ERROR: $module is licensed $found_license but the lock says $expect_license"
      failed=1
    fi

    # The project prohibits Enterprise code. An OPL/EE licence on a module we
    # depend on is a hard stop, not a warning, however it got there.
    case "$found_license" in
      OPL*|OEEL*|Enterprise*|OEEL-1)
        echo "  ERROR: $module is licensed $found_license, which is Odoo Enterprise."
        echo "    The project prohibits Enterprise code. Stop and review."
        failed=1
        ;;
      LGPL*|AGPL*|GPL*|Other/*) ;;
      *)
        echo "  ERROR: $module has an unrecognised licence '$found_license'."
        echo "    Refusing to record an unreviewed licence as acceptable."
        failed=1
        ;;
    esac

    echo "    $module $found_version ($found_license)"
    echo "$module=$found_version:$found_license" >> "$OCA_DIR/$name.modules"
  done

  # ── Confirm no Enterprise module was materialised ──────────────────────────
  # Sparse checkout should have prevented this. Checking anyway costs nothing and
  # turns a silent policy failure into a loud one if the sparse set is ever
  # widened or disabled.
  ent="$(find "$dest" -maxdepth 1 -type d -name 'ent_*' -print -quit || true)"
  if [ -n "$ent" ]; then
    echo "  ERROR: $name materialised Enterprise module $(basename "$ent") (OPL-1)."
    echo "    The sparse checkout should have excluded it. Do not continue."
    failed=1
  fi
  fetched=$((fetched + 1))
done < "$LOCK"

if [ "$fetched" -eq 0 ]; then
  echo "ERROR: no repositories were parsed from $LOCK_FILE."
  echo "Refusing to report success having fetched nothing."
  exit 1
fi

# ── Final Enterprise sweep across everything fetched ──────────────────────────
refuse_enterprise "$OCA_DIR"

if [ "$failed" -ne 0 ]; then
  echo
  echo "One or more repositories did not resolve cleanly. See errors above."
  echo "The addons path is not trustworthy; do not run a payroll against it."
  exit 1
fi

echo
echo "Dependencies ready in $OCA_DIR, all at locked revisions."
echo "Module licences recorded in $OCA_DIR/*.modules"
