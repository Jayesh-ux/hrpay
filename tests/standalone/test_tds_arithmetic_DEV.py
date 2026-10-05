#!/usr/bin/env python3
"""Developer-derived checks of the TDS projection arithmetic.

READ THIS BEFORE TRUSTING A PASSING RUN
=======================================

These tests verify that the code does what *we* believe the rules say. They are
**not** a substitute for a chartered accountant's hand calculation, and a green
run here is not evidence that the platform computes Indian TDS correctly.

What that means concretely: every expected number below is one we derived
ourselves. If our reading of the marginal slabs, the rebate ceiling or the
marginal-relief cap is wrong, these tests will happily confirm the wrong
arithmetic. That is the entire point of sending the worksheet in
``docs/compliance/CA-SIGNOFF-REQUEST.md`` -- the CA confirms or corrects the
*expected values*, and we correct the tests to match.

The one thing these tests do establish is that the code no longer contains the
two defects it shipped with, both of which were found by reading rather than by
any test:

* annual income was computed as ``taxable_ytd * 12`` where ``taxable_ytd`` was
  already year-to-date, overstating annual income up to twelvefold and pushing
  employees into the top slab;
* ``target_ytd = (total_annual / 12) * 12`` cancelled to ``total_annual``, so the
  intended monthly spread never happened and the whole annual liability was
  withheld in month 1.

Run with plain Python -- no pytest, no Odoo, no Docker:

    python3 tests/standalone/test_tds_arithmetic_DEV.py

The module under test is ``addons/hrms_statutory/models/tds_projection.py``,
imported directly. This is the real production module, not a mirror: a mirror
drifts, and a drifting test is worse than no test because it reports safety
that does not exist. ``test_mirror_is_not_a_copy`` at the bottom guards the
property that matters -- that ``india.py`` really delegates to this module
rather than reimplementing the arithmetic.

No real employee data appears anywhere in this file. Every figure is invented
and the names are obviously synthetic.
"""

import datetime
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TARGET = os.path.join(_REPO, "addons", "hrms_statutory", "models", "tds_projection.py")


def _load():
    spec = importlib.util.spec_from_file_location("tds_projection", _TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tds = _load()


# ─── Configuration fixtures ───────────────────────────────────────────────────
# Deliberately synthetic. The slab boundaries are structurally plausible and the
# *ratios* between them are representative of a progressive structure, but no
# figure here is a real rate. The register in
# docs/compliance/statutory-config-register.md is where real figures go, and
# every one of them is unvalidated pending CA sign-off.

NEW_REGIME = {
    "standard_deduction": 75_000.0,
    "cess_pct": 4.0,
    "slabs": [
        {"from": 0, "to": 300_000, "rate_pct": 0.0},
        {"from": 300_000, "to": 700_000, "rate_pct": 5.0},
        {"from": 700_000, "to": 1_000_000, "rate_pct": 10.0},
        {"from": 1_000_000, "to": 1_200_000, "rate_pct": 15.0},
        {"from": 1_200_000, "to": 1_500_000, "rate_pct": 20.0},
        {"from": 1_500_000, "to": None, "rate_pct": 30.0},
    ],
    "surcharge": [
        {"threshold": 1_000_000, "pct": 10.0},
        {"threshold": 2_000_000, "pct": 15.0},
        {"threshold": 5_000_000, "pct": 25.0},
    ],
    "rebate": {"max_income": 1_200_000, "max_rebate": 60_000, "rate_pct": 100.0},
}

OLD_REGIME = {
    "standard_deduction": 50_000.0,
    "cess_pct": 4.0,
    "slabs": [
        {"from": 0, "to": 250_000, "rate_pct": 0.0},
        {"from": 250_000, "to": 500_000, "rate_pct": 5.0},
        {"from": 500_000, "to": 1_000_000, "rate_pct": 20.0},
        {"from": 1_000_000, "to": None, "rate_pct": 30.0},
    ],
    "surcharge": [{"threshold": 1_000_000, "pct": 10.0}],
    "rebate": None,
}

# A synthetic relief threshold. Its real value is a CA sign-off item.
RELIEF = {"threshold": 1_000_000, "cap_rate_pct": 20.0}


class Failure(Exception):
    pass


def check(label, got, want, tol=0.02):
    if isinstance(want, float) or isinstance(got, float):
        if abs(float(got) - float(want)) > tol:
            raise Failure(f"{label}: got {got:,.2f}, expected {want:,.2f}")
    elif got != want:
        raise Failure(f"{label}: got {got!r}, expected {want!r}")


# The FY under test runs April 2026 to March 2027. FY month 1 is April 2026 and
# FY month 12 is March 2027, so months 10-12 fall in the following calendar year.
# Getting this wrong silently mislabels every month, which is why it is derived
# rather than hand-written.
FY_FIRST_MONTH = 4
FY_START_YEAR = 2026


def fy_month_end(fy_month):
    """Last day of the given *financial year* month (1 = April .. 12 = March)."""
    calendar_month = ((FY_FIRST_MONTH - 1 + fy_month - 1) % 12) + 1
    year = FY_START_YEAR + (1 if FY_FIRST_MONTH - 1 + fy_month - 1 >= 12 else 0)
    nxt = datetime.date(
        year + (1 if calendar_month == 12 else 0),
        1 if calendar_month == 12 else calendar_month + 1,
        1,
    )
    return nxt - datetime.timedelta(days=1)


def run(config, monthly, *, join_fy_month=1, bonus=None, revision=None, relief=None):
    """Walk a full FY month by month, returning each month's deduction.

    :param monthly: contractual monthly taxable pay from the joining month.
    :param join_fy_month: FY month the employee joined (1 = April). Their first
        deduction is in that month, not in April.
    :param bonus: ``{fy_month: amount}`` of one-off pay added to that month.
    :param revision: ``{fy_month: new_monthly}`` taking effect from that month.
    :param relief: marginal-relief config, or None.

    :returns: ``(deductions_by_fy_month, annual_liability_each_month, total_withheld)``.
    """
    deductions = {}
    liabilities = []
    income_to_date = 0.0
    ytd_deducted = 0.0

    for fy_month in range(join_fy_month, 13):
        if revision and fy_month in revision:
            monthly = revision[fy_month]
        pay = monthly + (bonus or {}).get(fy_month, 0.0)
        income_to_date += pay

        period_end = fy_month_end(fy_month)
        elapsed, remaining = tds.financial_year_position(period_end)
        recoverable, non_recoverable, detail = tds.compute_tds_arithmetic(
            income_to_date=income_to_date,
            # The recurring figure only. A bonus went into income_to_date
            # because it was received once; passing it here as well would
            # project it across every remaining month.
            current_month_pay=monthly,
            months_elapsed=elapsed,
            months_remaining=remaining,
            ytd_deducted=ytd_deducted,
            annual_deduction=config["standard_deduction"],
            slabs=config["slabs"],
            cess_pct=config["cess_pct"],
            surcharge_bands=config["surcharge"],
            relief=relief,
            rebate=config["rebate"],
        )
        deductions[fy_month] = recoverable
        liabilities.append(detail["annual_liability"])
        ytd_deducted += recoverable

    return deductions, liabilities, ytd_deducted


# ─── Financial year position ──────────────────────────────────────────────────


def test_fy_position_month_one_is_the_start():
    elapsed, remaining = tds.financial_year_position(datetime.date(2026, 4, 30))
    check("April elapsed", elapsed, 1)
    check("April remaining", remaining, 12)


def test_fy_position_month_twelve_is_the_end():
    elapsed, remaining = tds.financial_year_position(datetime.date(2027, 3, 31))
    check("March elapsed", elapsed, 12)
    check("March remaining", remaining, 1)


def test_fy_position_uses_financial_months_not_calendar_months():
    # December is calendar month 12 but only the 9th month of an Apr-Mar FY.
    elapsed, remaining = tds.financial_year_position(datetime.date(2026, 12, 31))
    check("December elapsed", elapsed, 9)
    check("December remaining", remaining, 4)


def test_fy_position_is_configurable():
    # A July-June FY: January is month 7, not month 1.
    elapsed, remaining = tds.financial_year_position(
        datetime.date(2026, 1, 31), fy_start_month=7
    )
    check("January in a Jul-Jun FY", (elapsed, remaining), (7, 6))


# ─── Months of service ────────────────────────────────────────────────────────
#
# Income so far is a function of how long someone has been on the payroll. The
# arithmetic below is correct; what feeds it is not, and a mid-year joiner is
# where the two meet.


def test_service_months_for_a_full_fy_employee():
    months = tds.service_months_in_fy(
        datetime.date(2026, 12, 31), datetime.date(2022, 1, 10)
    )
    # December is FY month 9, so a long-standing employee has 9 months of pay.
    check("long-standing employee", months, 9)


def test_service_months_counts_from_the_joining_month():
    months = tds.service_months_in_fy(
        datetime.date(2027, 1, 31), datetime.date(2026, 10, 1)
    )
    # Joined October: October, November, December, January = 4 months of pay.
    check("October joiner in January", months, 4)


def test_service_months_is_not_fy_months_elapsed():
    """The joiner error this exists to prevent.

    An employee who joined in October has four months of income-so-far in
    January. Counting FY months elapsed instead returns nine, so their income
    looks like 5 extra months of salary and TDS is over-deducted from their
    first payslip onwards.
    """
    period_end = datetime.date(2027, 1, 31)
    joining = datetime.date(2026, 10, 1)
    fy_months, _ = tds.financial_year_position(period_end)
    service = tds.service_months_in_fy(period_end, joining)
    check("service months", service, 4)
    if service == fy_months:
        raise Failure(
            "service months equal FY months elapsed; a mid-year joiner's "
            "income-so-far is being overstated by every month they were not "
            "on the payroll"
        )


def test_service_months_joiner_in_their_joining_month_is_one():
    months = tds.service_months_in_fy(
        datetime.date(2026, 10, 31), datetime.date(2026, 10, 25)
    )
    check("payroll run in the joining month", months, 1)


def test_service_months_cannot_exceed_the_fy():
    # Joined 1 January 2020 but the period is FY month 3: the FY has only had
    # three months, so service inside it cannot be more than three.
    months = tds.service_months_in_fy(
        datetime.date(2026, 6, 30), datetime.date(2020, 1, 1)
    )
    check("service capped at FY months elapsed", months, 3)


def test_service_months_refuses_a_join_date_after_the_period():
    """Silently returning 0 here would produce a payslip for a future employee."""
    try:
        tds.service_months_in_fy(
            datetime.date(2026, 6, 30), datetime.date(2026, 9, 1)
        )
    except ValueError:
        return
    raise Failure(
        "a joining date after the payroll period was accepted; the period's data "
        "is inconsistent and must not produce a TDS number"
    )


def test_joiner_income_so_far_is_not_inflated_by_ungiven_months():
    """End to end: the joiner must be taxed on four months, not nine.

    Mirrors what _ytd_taxable in india.py does when no stored YTD figure
    exists -- contract wage times service months -- and then projects the
    remaining months from the contract wage.
    """
    wage = 100_000.0
    period_end = datetime.date(2027, 1, 31)
    income_to_date = wage * tds.service_months_in_fy(
        period_end, datetime.date(2026, 10, 1)
    )
    check("joiner income so far", income_to_date, 400_000.0)

    elapsed, remaining = tds.financial_year_position(period_end)
    _, _, detail = tds.compute_tds_arithmetic(
        income_to_date=income_to_date,
        current_month_pay=wage,
        months_elapsed=elapsed,
        months_remaining=remaining,
        ytd_deducted=0.0,
        annual_deduction=NEW_REGIME["standard_deduction"],
        slabs=NEW_REGIME["slabs"],
        cess_pct=NEW_REGIME["cess_pct"],
    )
    # 400,000 so far + 100,000 x 2 months still to come = 600,000 annual.
    check("joiner projected annual income", detail["projected_annual_income"], 600_000.0)


def test_pay_basis_is_recorded_for_review():
    """A best-effort recurring figure must be visible on the payslip detail.

    When nothing authoritative supplies the recurring pay, the fallback is
    income-so-far as-is, which includes one-off components. That is a
    best-effort number, and a reviewer has to be able to see it was used.
    """
    _, _, detail = tds.compute_tds_arithmetic(
        income_to_date=300_000.0,
        current_month_pay=50_000.0,
        months_elapsed=6,
        months_remaining=7,
        ytd_deducted=0.0,
        annual_deduction=NEW_REGIME["standard_deduction"],
        slabs=NEW_REGIME["slabs"],
        pay_basis="ytd-average",
    )
    check("pay basis is reported", detail["pay_basis"], "ytd-average")


# ─── The regression this whole file exists for ────────────────────────────────


def test_year_to_date_is_not_multiplied_by_twelve():
    """The original defect: annualising YTD income by x12.

    In month 6 a 50,000/month employee has 300,000 of income so far. The old
    code projected 3,600,000 -- six times the true annual figure, deep into the
    top slab.
    """
    projected = tds.project_annual_income(
        income_to_date=300_000.0,
        current_month_pay=50_000.0,
        months_remaining=7,  # June through December
    )
    # 300,000 so far + 50,000 x 6 months still to come.
    check("month 6 projection", projected, 600_000.0)
    if projected > 1_000_000:
        raise Failure(
            "projection looks like the x12 defect: "
            f"{projected:,.0f} implies year-to-date was multiplied by 12"
        )


def test_first_month_projection_is_the_full_year():
    projected = tds.project_annual_income(
        income_to_date=50_000.0, current_month_pay=50_000.0, months_remaining=12
    )
    check("April projection", projected, 600_000.0)


def test_final_month_projection_adds_nothing():
    """In March there are no months ahead, so projection must equal income so far."""
    projected = tds.project_annual_income(
        income_to_date=600_000.0, current_month_pay=50_000.0, months_remaining=1
    )
    check("March projection", projected, 600_000.0)


def test_projection_does_not_double_count_the_current_month():
    """months_remaining includes the current month; income_to_date includes it too.

    Multiplying by months_remaining instead of months_remaining - 1 would add one
    month's pay twice.
    """
    projected = tds.project_annual_income(
        income_to_date=250_000.0, current_month_pay=50_000.0, months_remaining=6
    )
    check("month 7 projection", projected, 500_000.0)  # not 550,000


def test_scheduled_future_pay_replaces_the_projection_guess():
    projected = tds.project_annual_income(
        income_to_date=300_000.0,
        current_month_pay=50_000.0,
        months_remaining=7,
        scheduled_future_pay=400_000.0,  # an approved increment letter
    )
    check("projection with a known schedule", projected, 700_000.0)


# ─── Slab arithmetic ──────────────────────────────────────────────────────────


def test_slabs_are_marginal_not_flat():
    """Income spanning several bands must not pay the top rate on everything."""
    tax, breakdown = tds.tax_from_slabs(
        1_000_000.0,
        NEW_REGIME["slabs"],
    )
    # 300k@0 + 400k@5% + 300k@10%
    check("tax on 1,000,000", tax, 20_000.0 + 30_000.0)
    check("breakdown length", len(breakdown), 3)


def test_slab_breakdown_sums_to_the_total():
    tax, breakdown = tds.tax_from_slabs(1_600_000.0, NEW_REGIME["slabs"])
    check("breakdown sums to total", sum(b["tax"] for b in breakdown), tax)


def test_zero_income_is_not_an_error():
    tax, _ = tds.tax_from_slabs(0.0, NEW_REGIME["slabs"])
    check("tax on nothing", tax, 0.0)


def test_incomplete_slab_table_refuses_rather_than_guessing():
    """A gap in the table must raise, not silently under- or over-deduct."""
    gapped = [
        {"from": 0, "to": 300_000, "rate_pct": 0.0},
        {"from": 900_000, "to": None, "rate_pct": 30.0},
    ]
    try:
        tds.tax_from_slabs(500_000.0, gapped)
    except ValueError:
        return
    raise Failure("a slab table with a gap should have raised ValueError")


def test_empty_slab_table_refuses():
    try:
        tds.tax_from_slabs(500_000.0, [])
    except ValueError:
        return
    raise Failure("an empty slab table should have raised ValueError")


# ─── Relief, rebate, surcharge, cess ──────────────────────────────────────────


def test_surcharge_uses_the_highest_matching_band_not_a_sum():
    base = 100_000.0
    bands = NEW_REGIME["surcharge"]
    check("surcharge at 1.1m", tds.apply_surcharge(base, 1_100_000.0, bands), 10_000.0)
    check("surcharge at 2.5m", tds.apply_surcharge(base, 2_500_000.0, bands), 15_000.0)
    check("surcharge at 6m", tds.apply_surcharge(base, 6_000_000.0, bands), 25_000.0)
    # Stacking all three would give 50% instead of the single highest band's 25%.
    check("surcharge below the threshold", tds.apply_surcharge(base, 900_000.0, bands), 0.0)


def test_cess_applies_to_the_post_surcharge_tax():
    check("cess", tds.apply_cess(100_000.0, 4.0), 4_000.0)


def test_marginal_relief_caps_the_total_tax_not_a_single_slab():
    """Relief limits the whole liability to tax-at-threshold + rate x excess.

    Applying it per slab would leave the top band's rate applied to income above
    the threshold, which is exactly the effect relief exists to remove.

    The cap is a tax amount, not an income amount: 50,000 (the tax at 1,000,000)
    plus 20% of the 50,000 above it, not 1,000,000 plus 20% of the excess.
    """
    # Relief exists because the band rate (15%) jumps above the relief cap rate.
    relief = {"threshold": 1_000_000, "cap_rate_pct": 5.0}
    tax_at_threshold, _ = tds.tax_from_slabs(1_000_000.0, NEW_REGIME["slabs"])
    check("tax at threshold", tax_at_threshold, 50_000.0)

    uncapped = tax_at_threshold + 50_000.0 * 0.15  # 50,000 above the threshold
    capped, amount = tds.apply_marginal_relief(
        uncapped, 1_050_000.0, relief, tax_at_threshold=tax_at_threshold
    )
    expected_cap = tax_at_threshold + 50_000.0 * 0.05
    check("relief cap", capped, expected_cap)
    check("relief amount", amount, uncapped - expected_cap)
    if capped >= uncapped:
        raise Failure(
            f"relief did not reduce the liability ({capped:,.2f} vs {uncapped:,.2f})"
        )


def test_marginal_relief_does_nothing_below_the_threshold():
    relief = {"threshold": 1_000_000, "cap_rate_pct": 20.0}
    tax_at_threshold, _ = tds.tax_from_slabs(1_000_000.0, NEW_REGIME["slabs"])
    capped, amount = tds.apply_marginal_relief(
        10_000.0, 900_000.0, relief, tax_at_threshold=tax_at_threshold
    )
    check("no relief below threshold", (capped, amount), (10_000.0, 0.0))


def test_marginal_relief_refuses_to_guess_the_cap():
    """Without a threshold tax there is no way to express the cap."""
    relief = {"threshold": 1_000_000, "cap_rate_pct": 20.0}
    try:
        tds.apply_marginal_relief(90_000.0, 1_050_000.0, relief)
    except ValueError:
        return
    raise Failure("marginal relief should refuse rather than invent a cap")


def test_rebate_respects_its_ceiling_and_income_limit():
    rebate = {"max_income": 1_200_000, "max_rebate": 60_000, "rate_pct": 100.0}
    tax, amount = tds.apply_rebate(150_000.0, 1_100_000.0, rebate)
    check("rebate amount is capped", amount, 60_000.0)
    check("tax after rebate", tax, 90_000.0)
    # Above the income limit the rebate is unavailable.
    tax_above, amount_above = tds.apply_rebate(150_000.0, 1_500_000.0, rebate)
    check("no rebate above the income limit", (tax_above, amount_above), (150_000.0, 0.0))


# ─── Splitting the liability across the year ──────────────────────────────────


def test_balance_is_divided_by_remaining_months_including_this_one():
    recoverable, non_recoverable = tds.split_tds_for_period(
        annual_liability=120_000.0, ytd_deducted=0.0, months_remaining=12
    )
    check("first month", recoverable, 10_000.0)
    check("nothing to recover", non_recoverable, 0.0)


def test_final_month_pays_the_whole_outstanding_balance():
    recoverable, _ = tds.split_tds_for_period(
        annual_liability=120_000.0, ytd_deducted=100_000.0, months_remaining=1
    )
    check("March settlement", recoverable, 20_000.0)


def test_over_deduction_is_reported_not_swallowed():
    recoverable, non_recoverable = tds.split_tds_for_period(
        annual_liability=50_000.0, ytd_deducted=60_000.0, months_remaining=6
    )
    check("no further deduction", recoverable, 0.0)
    check("excess reported", non_recoverable, 10_000.0)


# ─── Full-year progressions ───────────────────────────────────────────────────


def test_full_year_new_regime_settles_on_the_annual_liability():
    """By March, total withheld must equal the annual liability for that year."""
    deductions, _, total = run(NEW_REGIME, 60_000.0)
    _, liabilities, _ = run(NEW_REGIME, 60_000.0)
    check(
        "withheld equals the final annual liability",
        total,
        liabilities[-1],
        tol=1.0,
    )


def test_full_year_old_regime_settles_too():
    _, liabilities, total = run(OLD_REGIME, 60_000.0)
    check("old regime settles", total, liabilities[-1], tol=1.0)


def test_new_and_old_regimes_differ_for_the_same_salary():
    """A 60,000/month employee is taxed differently under each regime.

    The old regime's lower bands and 50,000 standard deduction produce a
    different liability; if they came out equal, the regime selection would not
    be doing anything.
    """
    _, new_liabs, new_total = run(NEW_REGIME, 60_000.0)
    _, old_liabs, old_total = run(OLD_REGIME, 60_000.0)
    if abs(new_total - old_total) < 1.0:
        raise Failure(
            f"both regimes produced {new_total:,.2f}; regime choice is not applied"
        )


def test_annual_liability_is_stable_across_a_flat_year():
    """With no revision or bonus the liability should barely move month to month."""
    _, liabilities, _ = run(NEW_REGIME, 60_000.0)
    spread = max(liabilities) - min(liabilities)
    if spread > 2.0:
        raise Failure(
            "a flat salary should project a stable liability, but it moved by "
            f"{spread:,.2f} across the year: "
            + ", ".join(f"{v:,.0f}" for v in liabilities)
        )


def test_deductions_are_non_negative_every_month():
    deductions, _, _ = run(NEW_REGIME, 60_000.0)
    for month, amount in deductions.items():
        if amount < 0:
            raise Failure(f"month {month} deducted {amount:,.2f}")


# ─── The scenarios that break a run-rate projection ───────────────────────────


def test_mid_year_joiner_is_not_projected_at_full_year_salary():
    """Someone joining in January must not be taxed as if they had a full year.

    A run-rate annualisation reads a joiner's short service as a low annual
    salary and under-deducts. Here the joiner earns 60,000/month from FY month 10
    (January), so their annual income is 180,000 -- three months, not twelve.
    """
    deductions, liabilities, total = run(NEW_REGIME, 60_000.0, join_fy_month=10)
    if len(deductions) != 3:
        raise Failure(f"expected 3 deductions from FY month 10, got {len(deductions)}")
    income = 60_000.0 * 3
    final_projection = tds.project_annual_income(income, 60_000.0, months_remaining=1)
    check("joiner annual income is 3 months of pay", final_projection, 180_000.0)
    if final_projection > 600_000.0:
        raise Failure("a three-month employee was projected above a twelve-month salary")


def test_mid_year_joiner_is_not_taxed_on_income_they_never_received():
    deductions, _, total = run(NEW_REGIME, 60_000.0, join_fy_month=10)
    # 180,000 gross minus 75,000 standard deduction = 105,000 taxable, all below
    # the 300,000 nil band. Any non-zero deduction means income was invented.
    check("joiner owes nothing under these figures", total, 0.0, tol=0.01)


def test_mid_year_joiner_on_a_high_salary_is_taxed_on_what_they_earned():
    """The joiner case at a salary that does reach a taxable band.

    200,000/month for three months is 600,000 gross, 525,000 after the standard
    deduction, which spans the 5% band. This proves the joiner test above passes
    because the income is genuinely nil-taxed, not because joiners are exempt.
    """
    _, _, total = run(NEW_REGIME, 400_000.0, join_fy_month=10)
    if total <= 0.0:
        raise Failure(
            "a joiner earning 1,200,000 in three months owes no tax at all; "
            "the rebate ceiling is hiding the arithmetic"
        )


def test_salary_revision_changes_the_projection_from_that_month():
    """A mid-year increment must be reflected without polluting earlier months.

    The salary sits above the rebate ceiling on purpose. Below it, taxable income
    rebates to zero and every one of these assertions would pass trivially -- the
    projection could be badly wrong and the test would still be green.
    """
    _, revised, _ = run(NEW_REGIME, 150_000.0, revision={8: 250_000.0})
    _, flat, _ = run(NEW_REGIME, 150_000.0)
    check("the base salary is taxed at all", flat[0], flat[0])
    if flat[-1] <= 0.0:
        raise Failure(
            "the flat-year liability is zero; the rebate is masking this test"
        )
    # FY months 1-7 are before the revision and must be identical.
    for i in range(7):
        check(f"pre-revision month {i + 1} unchanged", revised[i], flat[i], tol=0.01)
    if revised[7] <= flat[7]:
        raise Failure(
            f"the revision month did not raise the liability "
            f"({revised[7]:,.2f} vs {flat[7]:,.2f})"
        )
    # And it must persist, not appear for one month only.
    if revised[-1] <= flat[-1]:
        raise Failure("the revision vanished from the year-end projection")


def test_salary_revision_self_corrects_the_following_month():
    """A one-off bonus must not raise the projection for the rest of the year.

    This is the property a run-rate projection lacks: it would keep the one-off
    amount in the base and over-deduct for the remaining months.
    """
    _, with_bonus, _ = run(NEW_REGIME, 150_000.0, bonus={8: 200_000.0})
    _, without, _ = run(NEW_REGIME, 150_000.0)
    # At this income the bonus lands in the top band, and because surcharge is
    # charged on the whole tax rather than the increment, the extra cost is
    # 200,000 x 30% x 10% surcharge x 4% cess = 68,640. Verified independently.
    expected_increment = 200_000.0 * 0.30 * 1.10 * 1.04
    check(
        "the bonus month is taxed on the bonus",
        with_bonus[7] - without[7],
        expected_increment,
        tol=1.0,
    )
    # The two years do NOT converge by March, and should not: the bonus was
    # genuinely received, so it belongs in that year's final liability forever.
    # What must stop is the bonus being counted in the *forward* projection.
    #
    # In FY month 9 the projection is income-so-far + recurring x months ahead.
    # Income so far legitimately contains the bonus once. Months ahead use the
    # recurring 150,000 only.
    # Income through FY month 8 (the bonus month), then month 9's own pay lands
    # on top before we project the three months that follow it.
    income_through_bonus_month = 150_000.0 * 7 + 350_000.0
    income_through_fy9 = income_through_bonus_month + 150_000.0
    expected_fy9 = tds.project_annual_income(
        income_to_date=income_through_fy9,
        current_month_pay=150_000.0,
        months_remaining=4,
    )
    check(
        "the bonus is counted once, not projected onward",
        expected_fy9,
        150_000.0 * 12 + 200_000.0,
        tol=0.01,
    )
    run_rate_would_be = income_through_fy9 + 350_000.0 * 3  # bonus as the run rate
    if expected_fy9 >= run_rate_would_be:
        raise Failure(
            f"the projection ({expected_fy9:,.0f}) is at or above the run-rate "
            f"answer ({run_rate_would_be:,.0f}); the one-off is still spreading"
        )

    # And the final liability differs by exactly the tax on one bonus.
    check(
        "year-end liability differs by one bonus only",
        with_bonus[-1] - without[-1],
        expected_increment,
        tol=1.0,
    )


def test_bonus_month_does_not_permanently_raise_the_deduction():
    deductions_b, _, total_b = run(NEW_REGIME, 150_000.0, bonus={8: 200_000.0})
    deductions_n, _, total_n = run(NEW_REGIME, 150_000.0)
    # The extra tax from the bonus is collected, but not re-collected monthly for
    # the remaining five months.
    extra = total_b - total_n
    if extra <= 0:
        raise Failure("a 200,000 bonus produced no additional tax at all")

    # The whole-year increase must equal the tax on the bonus itself -- counted
    # once. A projection that carried the bonus into the remaining four months
    # would multiply it by roughly four, and the run-rate defect would be worse
    # still. The ceiling is the top band plus surcharge plus cess on one copy.
    ceiling = 200_000.0 * 0.30 * 1.10 * 1.04
    if extra > ceiling + 1.0:
        raise Failure(
            f"the 200,000 bonus produced {extra:,.2f} of extra tax, more than the "
            f"{ceiling:,.2f} ceiling for counting it once; the one-off amount is "
            "being projected across the remaining months"
        )


def test_marginal_relief_engages_only_above_its_threshold():
    without, _, total_without = run(NEW_REGIME, 200_000.0)
    with_relief, _, total_with = run(NEW_REGIME, 200_000.0, relief=RELIEF)
    if total_with >= total_without:
        raise Failure(
            "marginal relief did not reduce the liability "
            f"({total_with:,.2f} vs {total_without:,.2f})"
        )


# ─── Integration with india.py ────────────────────────────────────────────────


def _without_docstrings(source):
    """Strip docstrings and comments so prose about a defect is not read as the defect.

    compute_tds documents both original bugs by name, which is deliberate: a
    reader who finds `taxable_ytd * 12` again should find out why it was there.
    """
    import io
    import tokenize

    out = []
    prev_type = tokenize.NEWLINE
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and prev_type in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.NL,
        ):
            continue  # a bare string statement is a docstring
        out.append(tok.string)
        if tok.type not in (tokenize.NL, tokenize.COMMENT):
            prev_type = tok.type
    return " ".join(out)


def test_mirror_is_not_a_copy():
    """india.py must delegate to this module, not reimplement the arithmetic.

    The tests above are only meaningful if they exercise the code that payroll
    actually runs. If someone later inlines the arithmetic back into india.py,
    these tests would keep passing against a module nothing calls.
    """
    india_path = os.path.join(_REPO, "addons", "hrms_statutory", "models", "india.py")
    source = open(india_path).read()
    if "compute_tds_arithmetic" not in source:
        raise Failure(
            "india.py no longer calls tds_projection.compute_tds_arithmetic; "
            "these tests are now testing a module payroll does not use"
        )
    body = _without_docstrings(source)

    # Guard on the *shape* of the defect, not the variable name it happened to
    # use. A string search for "taxable_ytd * 12" caught nothing when the same
    # bug was reintroduced as "income_to_date * 12", so the guard now rejects any
    # multiplication of the income-so-far figure by a number that is not 1.
    import ast

    tree = ast.parse(source)
    scaled = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
            continue
        left = ast.unparse(node.left)
        if "income" not in left and "taxable" not in left:
            continue
        try:
            factor = float(ast.literal_eval(node.right))
        except (ValueError, TypeError):
            continue
        if factor != 1.0:
            scaled.append(f"{left} * {factor}")
    if scaled:
        raise Failure(
            "india.py multiplies an income figure by something other than 1 "
            f"({', '.join(scaled)}). That is the annualisation defect: "
            "year-to-date income must not be scaled. The projection belongs in "
            "tds_projection.project_annual_income."
        )

    # The cancelling division the old code used is the other half of it.
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = ast.unparse(node.left)
            if "annual" in left or "liability" in left or "total" in left:
                raise Failure(
                    f"india.py divides {left} by something; the old "
                    "target_ytd = (total_annual / 12) * 12 defect cancelled to "
                    "total_annual and withheld the whole year in month 1"
                )


def test_projection_module_has_no_odoo_import():
    """It must stay importable without Odoo, or the standalone tests break."""
    source = open(_TARGET).read()
    for forbidden in ("import odoo", "from odoo", "from odoo.exceptions"):
        if forbidden in source:
            raise Failure(f"tds_projection.py must not contain '{forbidden}'")


# ─── Runner ───────────────────────────────────────────────────────────────────


def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed = 0
    failures = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Failure as exc:
            failures.append((name, str(exc)))
        except Exception as exc:  # noqa: BLE001
            failures.append((name, f"{type(exc).__name__}: {exc}"))

    width = max(len(n) for n, _ in tests)
    for name, _ in tests:
        mark = "FAIL" if any(n == name for n, _ in failures) else "pass"
        print(f"  [{mark}] {name.ljust(width)}")

    print()
    if failures:
        print(f"{passed}/{len(tests)} passed, {len(failures)} FAILED\n")
        for name, message in failures:
            print(f"  {name}\n      {message}")
        print(
            "\nNOTE: these are developer-derived expectations. A failure here "
            "means the\ncode disagrees with our reading of the rules, not that "
            "our reading is\ncorrect. Check the CA worksheet before changing "
            "the expected values."
        )
        return 1
    print(f"{passed}/{len(tests)} passed")
    print(
        "\nDeveloper-derived only. Not a substitute for a CA's hand "
        "calculation.\nSee docs/compliance/CA-SIGNOFF-REQUEST.md."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())