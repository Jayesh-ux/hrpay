# Run inside `odoo shell`. Verifies the statutory sign-off gate is still holding
# after an install: no catalog code may resolve to a usable value.
#
# Run by ops/run_odoo_tests.sh. Exits the script by printing a single marker line
# the caller greps for, because odoo shell does not propagate a useful exit code.
#
# Read-only apart from an explicit rollback: this check must not be able to change
# what it is inspecting.

from odoo import SUPERUSER_ID

MARKER_OK = "GATE_HOLDING"
MARKER_BAD = "GATE_BREACHED"

try:
    catalog = env["hrms.statutory.catalog"].with_user(SUPERUSER_ID)
    ctx = env["hrms.statutory.context"].with_user(SUPERUSER_ID)
    company = env.company.with_user(SUPERUSER_ID)

    codes = catalog.catalog_codes()
    resolved = []
    for code in codes:
        try:
            version = ctx.resolve(code, company)
        except Exception:
            continue
        resolved.append(f"  {code} -> version {version.id} state={version.state}")

    # Second, stronger check: no version row may exist outside draft. A validated
    # row anywhere in the table means something signed off without a human.
    stray = (
        env["hrms.statutory.rule.version"]
        .with_user(SUPERUSER_ID)
        .search([("state", "!=", "draft")])
    )
    validations = (
        env["hrms.statutory.rule.version"]
        .with_user(SUPERUSER_ID)
        .search([("validated_by", "!=", False)])
    )

    print(f"statutory codes in catalog: {len(codes)}")
    print(f"codes resolving to a value: {len(resolved)}")
    print(f"versions not in draft:      {len(stray)}")
    print(f"versions claiming a signer: {len(validations)}")

    if resolved or stray:
        print("The following resolved without a human sign-off and must not exist:")
        for line in resolved:
            print(line)
        for version in stray:
            print(f"  {version.rule_id.code} version {version.version} state={version.state}")
        print(MARKER_BAD)
    else:
        print(MARKER_OK)

except Exception as exc:  # noqa: BLE001
    # Never let an exception here read as "gate holding".
    print(f"gate check could not complete: {type(exc).__name__}: {exc}")
    print(MARKER_BAD)

finally:
    # A check must never leave a change behind.
    env.cr.rollback()