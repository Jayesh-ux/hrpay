# -*- coding: utf-8 -*-
"""Post-install seed hook.

Runs once when the module is installed. Its only job is to create the statutory
rule skeletons so the gap is visible and fillable, and then prove that the gap
still blocks payroll.

The second half matters as much as the first. A seeder that quietly created a
default rate "to get things working" would be the single most damaging thing in
this codebase, because it would look like a working payroll run. So after
seeding, the hook asserts that no catalog code resolves to a usable value, and
refuses to finish the install if any of them does.
"""

import logging

from odoo import SUPERUSER_ID

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    created = env["hrms.statutory.catalog"].with_user(SUPERUSER_ID).seed()
    _assert_nothing_is_live(env)
    _logger.info(
        "hrms_statutory: post_init_hook created %d rule skeleton(s). Every one "
        "remains unsigned-off, so payroll is blocked until a qualified "
        "professional signs off each value.",
        created,
    )


def _assert_nothing_is_live(env):
    """Fail the install if any seeded code is already usable.

    This is a belt-and-braces check on the working rule "never hardcode
    statutory rates". The seeder only writes rule rows, so nothing should resolve;
    if something does, either a version was seeded by hand or the sign-off gate
    has been weakened, and either way the database must not be left in a state
    that appears go-live ready.
    """
    catalog = env["hrms.statutory.catalog"].with_user(SUPERUSER_ID)
    ctx = env["hrms.statutory.context"].with_user(SUPERUSER_ID)
    company = env.company.with_user(SUPERUSER_ID)

    codes = catalog.catalog_codes()
    leaked = []
    for code in codes:
        try:
            version = ctx.resolve(code, company)
        except Exception:
            continue
        # Only a genuine sign-off counts as live. A draft row resolves to
        # nothing usable, but if one ever did, name it in the error.
        leaked.append(f"{code} -> version {version.id} ({version.state})")

    if leaked:
        raise RuntimeError(
            "hrms_statutory refused to finish installing: these statutory codes "
            "resolved to a usable value, which means a value was seeded without "
            "sign-off:\n  " + "\n  ".join(leaked) + "\n"
            "The working rule is that no statutory rate, cap or slab exists "
            "until a named payroll/tax professional validates it against a "
            "source. Fix the data, then reinstall."
        )

    _logger.info(
        "hrms_statutory: verified that all %d catalog codes are unresolved, so "
        "the sign-off gate is holding.",
        len(codes),
    )


def uninstall_hook(env):
    """Refuse to leave orphaned skeletons behind on uninstall.

    Not a safety feature so much as a courtesy: if the module is being removed
    by accident, the rules are still here and can be inspected.
    """
    count = env["hrms.statutory.rule"].with_user(SUPERUSER_ID).search_count([])
    if count:
        _logger.warning(
            "hrms_statutory: uninstalling with %d rule(s) still present. They "
            "will be removed with the module, which discards the evidence of "
            "which codes were configured. Export them first if that matters.",
            count,
        )


__all__ = ["post_init_hook", "uninstall_hook"]

# Odoo looks up hooks by name in the module's __init__ namespace.
_ = api  # keep the import meaningful for tooling that inspects this module