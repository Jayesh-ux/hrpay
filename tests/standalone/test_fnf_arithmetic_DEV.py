#!/usr/bin/env python3
"""Developer-derived checks of the final-settlement arithmetic.

READ THIS BEFORE TRUSTING A PASSING RUN
=======================================

Every expected number here is **ours**, not a professional's. No real employee
data and no real employer data appears anywhere in this file.

What these tests *do* establish is that these defects cannot return silently:

* **Leave accrual grew with the square of service months.** The code rebound
  ``months`` from the per-month accrual to the count of service months and then
  multiplied them, so 18 months of service entitled an employee to 324 days of
  leave. Every encashment amount derived from it was wrong, in the employee's
  favour, so it would have been paid without complaint and corrected at audit.
* **Leave encashment was always zero.** The accrual was read from
  ``IN.LEAVE.ACCRUAL_DAYS.<leave type>``, a code that was never in the catalog,
  and the resulting error was swallowed into ``0.0``. A statutory payment that is
  always zero and raises nothing is the worst combination available.
* **The daily wage was ``CTC / 365``** -- CTC is not statutory wages, and 365 is a
  year, not the divisor of a month.
* **The three-month average summed every payslip line**, so employer
  contributions were added to the basis and employee deductions netted off it, and
  an average over three months was divided by the day count of one month.
* **A negative settlement was reported as a bare negative net**, indistinguishable
  from a positive one, and deduction amounts were passed through ``abs()``.

Run with plain Python -- no pytest, no Odoo, no Docker:

    python3 tests/standalone/test_fnf_arithmetic_DEV.py
"""

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))

_PATH = os.path.join(_REPO, "addons", "hrms_fnf", "models",
                     "settlement_arithmetic.py")
_spec = importlib.util.spec_from_file_location("settlement_arithmetic", _PATH)
fnf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fnf)


class Failure(Exception):
    pass


def check(label, got, want, tol=0.01):
    if isinstance(want, (int, float)) and not isinstance(want, bool) and \
       isinstance(got, (int, float)) and not isinstance(got, bool):
        if abs(float(got) - float(want)) > tol:
            raise Failure(f"{label}: got {got:,.2f}, expected {want:,.2f}")
    elif got != want:
        raise Failure(f"{label}: got {got!r}, expected {want!r}")


def raises(fn, needle=""):
    try:
        fn()
    except ValueError as exc:
        if needle and needle.lower() not in str(exc).lower():
            raise Failure(f"refused with the wrong reason: {exc}")
        return str(exc)
    raise Failure("this should have been refused, but it returned a number")


# ─── Leave accrual ────────────────────────────────────────────────────────────


def test_accrual_is_linear_not_quadratic():
    """The defect: 18 months of service gave 324 days. Linear gives 27."""
    check("18 days a year, 18 months of service",
          fnf.accrued_leave_days(annual_days=18.0, months_of_service=18), 27.0)


def test_accrual_across_a_year_of_service():
    check("24 days a year, 12 months",
          fnf.accrued_leave_days(annual_days=24.0, months_of_service=12), 24.0)


def test_accrual_from_a_monthly_rate():
    check("1.5 a month, 18 months",
          fnf.accrued_leave_days(monthly_days=1.5, months_of_service=18), 27.0)


def test_as_of_months_overrides_the_service_count():
    """The caller has usually already counted the months."""
    check("counted by the caller",
          fnf.accrued_leave_days(annual_days=18.0, months_of_service=99,
                                 as_of_months=6), 9.0)


def test_accrual_needs_a_rate():
    """A zero accrual means nothing is owed; an absent rate means we do not know."""
    raises(lambda: fnf.accrued_leave_days(months_of_service=18), "exactly one")


def test_accrual_refuses_both_rates_at_once():
    raises(lambda: fnf.accrued_leave_days(annual_days=18.0, monthly_days=1.5,
                                           months_of_service=18),
           "ambiguous")


def test_accrual_needs_service_months():
    raises(lambda: fnf.accrued_leave_days(annual_days=18.0), "months of service")


def test_accrual_refuses_negative_service():
    raises(lambda: fnf.accrued_leave_days(annual_days=18.0, months_of_service=-1))


def test_no_service_is_no_accrual():
    check("zero", fnf.accrued_leave_days(annual_days=18.0, months_of_service=0), 0.0)


def test_service_months_counts_whole_months():
    import datetime

    check("1 Jan to 1 Mar", fnf.service_months(datetime.date(2024, 1, 1),
                                               datetime.date(2024, 3, 1)), 2)
    check("1 Jan to 28 Feb", fnf.service_months(datetime.date(2024, 1, 1),
                                                datetime.date(2024, 2, 28)), 1)


# ─── Daily wage ───────────────────────────────────────────────────────────────


def test_daily_wage_uses_the_month_not_the_year():
    """The defect: CTC/365. 30,000 over a 28-day February is 1,071.43 a day."""
    check("February", fnf.daily_wage(30000.0, 28), 1071.43)
    check("March", fnf.daily_wage(30000.0, 31), 967.74)


def test_daily_wage_refuses_a_zero_divisor():
    """A zero divisor previously produced an encashment of zero with no error."""
    raises(lambda: fnf.daily_wage(30000.0, 0), "must be positive")


def test_daily_wage_requires_a_wage_figure():
    raises(lambda: fnf.daily_wage(None, 30), "not configured")


def test_ctc_basis_must_be_asked_for_explicitly():
    """Passing CTC is allowed, but it has to be a decision and not a default."""
    check("asked for", fnf.daily_wage(45000.0, 30, basis="ctc"), 1500.0)
    raises(lambda: fnf.daily_wage(30000.0, 30, basis="gross"), "unknown encashment")


# ─── Encashment and excess leave ──────────────────────────────────────────────


def test_encashment_of_unused_leave():
    r = fnf.encashment_for_leave(unused_days=10.0, daily_rate=1000.0)
    check("payable", r["encashable_amount"], 10000.0)
    check("nothing recovered", r["recoverable_amount"], 0.0)


def test_excess_leave_is_recovered():
    r = fnf.encashment_for_leave(unused_days=0.0, daily_rate=1000.0,
                                 excess_days=5.0)
    check("recovered", r["recoverable_amount"], 5000.0)


def test_carry_forward_absorbs_the_excess_first():
    """30 days of carry-forward absorbs 8 of 10 excess days."""
    r = fnf.encashment_for_leave(unused_days=0.0, daily_rate=500.0,
                                 excess_days=10.0, carry_forward_days=8.0)
    check("two days recoverable", r["recoverable_days"], 2.0)
    check("worth 1,000", r["recoverable_amount"], 1000.0)


def test_excess_inside_carry_forward_is_not_recovered():
    r = fnf.encashment_for_leave(unused_days=0.0, daily_rate=500.0,
                                 excess_days=5.0, carry_forward_days=30.0)
    check("nothing recovered", r["recoverable_amount"], 0.0)


def test_recovery_can_be_suppressed_for_absence_of_authority():
    """Recovering excess leave without authority is itself unlawful."""
    r = fnf.encashment_for_leave(unused_days=0.0, daily_rate=500.0,
                                 excess_days=10.0, recovery_permitted=False)
    check("nothing recovered", r["recoverable_amount"], 0.0)
    check("and it says so", r["recovery_suppressed"], True)


def test_encashment_and_recovery_of_the_same_leave_type():
    r = fnf.encashment_for_leave(unused_days=6.0, daily_rate=800.0,
                                 excess_days=4.0, carry_forward_days=1.0)
    check("encashable", r["encashable_amount"], 4800.0)
    check("three days recoverable", r["recoverable_days"], 3.0)
    check("worth 2,400", r["recoverable_amount"], 2400.0)


def test_encashment_refuses_negative_days():
    raises(lambda: fnf.encashment_for_leave(unused_days=-1.0, daily_rate=100.0))


def test_encashment_requires_a_rate():
    raises(lambda: fnf.encashment_for_leave(unused_days=5.0, daily_rate=None),
           "not configured")


# ─── Notice shortfall ─────────────────────────────────────────────────────────


def test_unserved_notice_is_a_positive_shortfall():
    check("90 required, 45 served",
          fnf.notice_shortfall_days(90, 45), 45)


def test_over_served_notice_is_negative_not_zero():
    """Negative means notice pay is owed to the employee, not a recovery."""
    check("30 required, 45 served",
          fnf.notice_shortfall_days(30, 45), -15)


def test_exactly_served_notice_is_nothing():
    check("zero", fnf.notice_shortfall_days(60, 60), 0)


def test_shortfall_recovery_amount():
    r = fnf.notice_shortfall_days(90, 45)
    out = fnf.notice_shortfall_recovery(r, daily_rate=2000.0,
                                        permits_recovery=True)
    check("45 days at 2,000", out["recovery_amount"], 90000.0)
    check("not suppressed", out["recovery_suppressed"], False)


def test_shortfall_is_not_recovered_without_authority():
    r = fnf.notice_shortfall_days(90, 45)
    out = fnf.notice_shortfall_recovery(r, daily_rate=2000.0,
                                        permits_recovery=False)
    check("nothing deducted", out["recovery_amount"], 0.0)
    check("but the shortfall is still reported", out["uncapped_amount"], 90000.0)
    check("suppressed", out["recovery_suppressed"], True)
    check("and the reason is recorded", len(out["notes"]), 1)


def test_contractual_recovery_ceiling_binds():
    r = fnf.notice_shortfall_days(90, 45)
    out = fnf.notice_shortfall_recovery(r, daily_rate=2000.0,
                                        permits_recovery=True,
                                        max_recoverable=30000.0)
    check("capped at the contract", out["recovery_amount"], 30000.0)
    check("uncapped value still shown", out["uncapped_amount"], 90000.0)
    check("noted", "contractually recoverable" in out["notes"][0], True)


def test_statutory_ceiling_binds_after_the_contractual_one():
    r = fnf.notice_shortfall_days(90, 45)
    out = fnf.notice_shortfall_recovery(r, daily_rate=2000.0,
                                        permits_recovery=True,
                                        max_recoverable=500000.0,
                                        ceiling=60000.0)
    check("capped at the statute", out["recovery_amount"], 60000.0)
    check("noted", "statutory limit" in out["notes"][0], True)


def test_shortfall_of_nothing_recovers_nothing():
    out = fnf.notice_shortfall_recovery(0, daily_rate=2000.0,
                                        permits_recovery=True)
    check("zero", out["recovery_amount"], 0.0)
    check("no notes", out["notes"], [])


def test_shortfall_recovery_requires_a_daily_rate():
    raises(lambda: fnf.notice_shortfall_recovery(10, daily_rate=None,
                                                 permits_recovery=True),
           "not configured")


def test_negative_shortfall_is_refused():
    """Over-served notice is a payment to the employee, not a negative recovery."""
    raises(lambda: fnf.notice_shortfall_recovery(-15, daily_rate=100.0,
                                                 permits_recovery=True))


def test_negative_notice_days_are_refused():
    raises(lambda: fnf.notice_shortfall_days(-90, 45))


# ─── Settlement netting ───────────────────────────────────────────────────────


def test_ordinary_settlement_nets():
    r = fnf.net_settlement(
        [{"amount": 50000.0}, {"amount": 12000.0}],
        [{"amount": 2000.0}, {"amount": 1500.0}],
    )
    check("gross", r["gross_payable"], 62000.0)
    check("deductions", r["total_deductions"], 3500.0)
    check("net", r["net_payable"], 58500.0)
    check("payable", r["amount_payable"], 58500.0)
    check("no recovery", r["recovery_due"], 0.0)
    check("not negative", r["is_negative_settlement"], False)


def test_deductions_greater_than_payables_report_a_recovery():
    """A negative settlement is a recovery from the employee, with consequences."""
    r = fnf.net_settlement([{"amount": 20000.0}], [{"amount": 45000.0}])
    check("net is negative", r["net_payable"], -25000.0)
    check("flagged", r["is_negative_settlement"], True)
    check("nothing payable", r["amount_payable"], 0.0)
    check("25,000 due from the employee", r["recovery_due"], 25000.0)


def test_netting_does_not_abs_the_deductions():
    """The defect: ``sum(abs(...))`` made the magnitude the only thing that counted."""
    r = fnf.net_settlement([{"amount": 10000.0}], [{"amount": 2500.0}])
    check("deduction subtracted, not added", r["net_payable"], 7500.0)


def test_a_negative_payable_line_is_refused():
    """Otherwise a shortfall hides inside a payment and reads as a positive net."""
    raises(lambda: fnf.net_settlement([{"amount": 50000.0}, {"amount": -1000.0}],
                                      []),
           "move it to the deduction side")


def test_a_negative_deduction_line_is_refused():
    raises(lambda: fnf.net_settlement([{"amount": 50000.0}],
                                      [{"amount": -1000.0}]),
           "positive magnitudes")


def test_a_negative_line_refused_even_when_the_net_would_look_right():
    """A -1,000 deduction and a +1,000 payable would cancel to a clean-looking zero."""
    raises(lambda: fnf.net_settlement([{"amount": 1000.0}],
                                      [{"amount": -1000.0}]),
           "positive magnitudes")


def test_exactly_zero_net_is_not_a_recovery():
    r = fnf.net_settlement([{"amount": 5000.0}], [{"amount": 5000.0}])
    check("net", r["net_payable"], 0.0)
    check("nothing payable", r["amount_payable"], 0.0)
    check("nothing recovered", r["recovery_due"], 0.0)
    check("and not called negative", r["is_negative_settlement"], False)


def test_a_payable_line_of_one_rupee_over_the_deductions():
    r = fnf.net_settlement([{"amount": 5000.0}], [{"amount": 4999.99}])
    check("net", r["net_payable"], 0.01)


def test_empty_sides_net_to_zero():
    r = fnf.net_settlement([], [])
    check("zero", r["net_payable"], 0.0)
    check("line count", r["line_count"], 0)


def test_bare_amounts_are_accepted_as_well_as_dicts():
    r = fnf.net_settlement([1000.0, 500.0], [250.0])
    check("gross", r["gross_payable"], 1500.0)
    check("net", r["net_payable"], 1250.0)


def test_a_missing_amount_key_reads_as_zero_not_an_exception():
    r = fnf.net_settlement([{"line_type": "gratuity"}], [])
    check("zero gross", r["gross_payable"], 0.0)


def test_line_count_is_reported():
    r = fnf.net_settlement([{"amount": 1.0}, {"amount": 2.0}], [{"amount": 3.0}])
    check("three lines", r["line_count"], 3)


def test_rounding_to_two_places_on_a_repeating_daily_rate():
    """Daily rates do not divide evenly, and the net must still reconcile."""
    r = fnf.net_settlement([{"amount": 173076.92}], [{"amount": 173076.91}])
    check("net", r["net_payable"], 0.01)
    check("rounded", round(r["net_payable"], 2), 0.01)


# ─── Structural guards ────────────────────────────────────────────────────────


def test_module_has_no_odoo_import():
    source = open(_PATH).read()
    for forbidden in ("import odoo", "from odoo", "odoo.exceptions"):
        if forbidden in source:
            raise Failure(f"settlement_arithmetic.py contains '{forbidden}'")


def test_no_mirrored_copies():
    """Both callers must import this module, not reimplement it."""
    for rel in (("addons", "hrms_fnf", "models", "encashment.py"),
                ("addons", "hrms_fnf", "models", "settlement.py")):
        source = open(os.path.join(_REPO, *rel)).read()
        if "settlement_arithmetic" not in source:
            raise Failure(
                f"{rel[-1]} no longer uses settlement_arithmetic; these tests are "
                f"now testing a module payroll does not use"
            )


def test_swallowed_exceptions_are_gone():
    """A statement that cannot be read must not read as a zero settlement."""
    source = open(os.path.join(_REPO, "addons", "hrms_fnf", "models",
                               "settlement.py")).read()
    for pattern in ("except Exception:\\n                statement = {}",
                    "abs(l[\"amount\"])"):
        if pattern in source:
            raise Failure(
                f"settlement.py still contains {pattern!r}; a settlement figure "
                f"that cannot be computed must be refused, not zeroed"
            )


def test_the_accrual_code_is_in_the_catalog():
    """The code the caller resolves must exist, or the lookup fails silently."""
    catalog = open(os.path.join(_REPO, "addons", "hrms_statutory", "models",
                                "catalog.py")).read()
    for code in ("IN.LEAVE.ACCRUAL_DAYS_PER_YEAR", "IN.FNF.ENCASHMENT_WAGE_BASIS",
                 "IN.PF.EMPLOYER_RATE", "IN.PF.EPS_ANNUAL_CEILING",
                 "IN.ESI.CONTRIBUTION_SCHEDULE"):
        if f'"{code}"' not in catalog:
            raise Failure(f"{code} is resolved by the engine but is not in the catalog")


# ─── Runner ───────────────────────────────────────────────────────────────────


def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            status = "pass"
        except Failure as exc:
            status = "FAIL"
            failures.append((name, str(exc)))
        print(f"  [{status}] {name}")
    print()
    for name, message in failures:
        print(f"FAILED {name}\n    {message}\n")
    print(f"{len(tests) - len(failures)}/{len(tests)} passed")
    print()
    print("Developer-derived only. Not a substitute for a CA's hand calculation.")
    print("See docs/compliance/CA-SIGNOFF-REQUEST.md.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
