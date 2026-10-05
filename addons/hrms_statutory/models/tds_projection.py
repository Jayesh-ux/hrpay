"""TDS projection arithmetic (Section 192) -- pure Python, no Odoo imports.

Why this file exists
--------------------
The previous implementation of this logic lived inside ``india.py`` and could
only be exercised by a running Odoo instance. Nothing about it was testable on a
machine without Docker, so it shipped with two arithmetic defects that no test
could catch (see the ``compute_tds`` docstring in ``india.py``).

Every function here takes and returns plain values -- no recordsets, no
``UserError``, no ORM. ``india.py`` is the only caller and it is responsible for
reading configuration and translating refusals into ``UserError``.

That separation is deliberate: ``tests/standalone/test_tds_arithmetic_DEV.py``
imports *this* module directly, so the tests exercise the code that actually
runs in payroll rather than a hand-maintained copy of it. A mirror would drift;
this cannot.

Financial year conventions
--------------------------
An Indian financial year runs April to March (``IN.FY_START_MONTH``). All month
arithmetic below is expressed in *elapsed months of the financial year* rather
than calendar month numbers, because a mid-year joiner and a calendar-year
calculation disagree and using the calendar month is precisely how the old
``taxable_ytd * 12`` bug arose.

Every threshold, slab boundary, rate, cess percentage, surcharge band, rebate
ceiling and marginal-relief figure is read from configuration by the caller and
passed in as an argument. Nothing numeric is hardcoded here, because statutory
values must be effective-dated and signed off by a named professional.
"""

# Financial year start month for India. Configurable per company in
# hrms_core_ext, but the default lives here so the arithmetic is self-describing.
IN_FY_START_MONTH = 4

MONTHS_IN_FY = 12


def financial_year_position(period_end, fy_start_month=IN_FY_START_MONTH):
    """Return where ``period_end`` sits inside its financial year.

    :param period_end: a ``datetime.date`` for the last day of the payroll period.
    :param fy_start_month: calendar month number the FY begins (4 = April).
    :returns: ``(months_elapsed, months_remaining)`` where both counts *include*
        the current month. ``months_elapsed`` is 1 in the FY's first month and
        12 in its last. ``months_remaining`` is 12 in the first month and 1 in
        the last.

    Both counts are measured against the *financial* year, so the sum is always
    ``MONTHS_IN_FY + 1``. The caller relies on that: ``months_remaining``
    becomes the divisor that spreads the year's remaining tax liability.
    """
    month = period_end.month
    # Elapsed: how many FY months have passed, current one included.
    elapsed = month - fy_start_month + 1
    if elapsed <= 0:
        # Before the FY start: we are in the previous FY's tail.
        elapsed += MONTHS_IN_FY
    if elapsed > MONTHS_IN_FY:
        # Defensive: a month later than the FY end should not silently produce
        # elapsed > 12. Callers get a nonsensical divisor otherwise.
        raise ValueError(
            f"period_end month {month} produced {elapsed} elapsed FY months "
            f"with fy_start_month={fy_start_month}"
        )
    return elapsed, MONTHS_IN_FY - elapsed + 1


def months_after_current(months_remaining):
    """Months strictly after the current one, within the same FY.

    ``income_to_date`` already contains the current month's pay, so projecting
    the rest of the year must add only the months that follow it. Using
    ``months_remaining`` directly would count the current month twice and
    overstate the annual income by exactly one month's pay.
    """
    if months_remaining < 1:
        raise ValueError(f"months_remaining must be >= 1, got {months_remaining}")
    return months_remaining - 1


def service_months_in_fy(period_end, joining_date=None, fy_start_month=IN_FY_START_MONTH):
    """Months of service in this financial year, up to and including ``period_end``.

    Income-so-far is a function of how long the employee has actually been on
    the payroll, not of how far through the financial year we are. Counting FY
    months instead of service months overstates a mid-year joiner's income by
    every month they were not here, and over-deducts TDS from them from their
    first payslip onwards -- the opposite of the error the projection below is
    designed to avoid.

    The joining month counts as a whole month of service. A joiner who starts on
    the 25th of a month is paid for a part of it, and treating that as a full
    month slightly overstates income-so-far in the joining month only; the
    alternative (a fractional month) would need a day-count rule this module
    deliberately does not invent.

    :param period_end: a ``datetime.date`` for the last day of the payroll period.
    :param joining_date: the employee's date of joining, or ``None`` when unknown.
    :param fy_start_month: calendar month number the FY begins (4 = April).
    :returns: service months in ``1..months_elapsed``, or ``0`` when the employee
        had not joined by ``period_end``.
    :raises ValueError: if the employee joined *after* ``period_end`` yet a
        non-zero service count was implied. That combination means the caller's
        data is inconsistent, and silently returning a number here would produce
        a plausible payslip for an employee who does not exist yet.
    """
    elapsed, _ = financial_year_position(period_end, fy_start_month)
    if joining_date is None:
        return elapsed

    if joining_date.year > period_end.year or (
        joining_date.year == period_end.year and joining_date.month > period_end.month
    ):
        raise ValueError(
            f"joining month {joining_date.year}-{joining_date.month:02d} is after "
            f"the payroll period ending {period_end.year}-{period_end.month:02d}; "
            "the employee cannot have income or TDS for this period"
        )

    # Whole months from the joining month to the period's month, inclusive.
    service = (period_end.year - joining_date.year) * MONTHS_IN_FY + (
        period_end.month - joining_date.month
    ) + 1
    # A joiner cannot have more service in the FY than the FY has months.
    return max(0, min(service, elapsed))


def project_annual_income(
    income_to_date,
    current_month_pay,
    months_remaining,
    scheduled_future_pay=None,
):
    """Project full-year taxable income as at the current month.

    Method (agreed with the CA review):

    1. income so far this financial year, plus
    2. the current month's pay multiplied by the months that follow it, or
       ``scheduled_future_pay`` where the future pay is already known
       (an approved increment letter, an agreed bonus schedule).

    This deliberately does **not** extrapolate from an average run rate. A
    run-rate projection is wrong in the cases that matter:

    * a mid-year joiner has fewer months of service than months of FY elapsed,
      so a run rate reads their short service as a low annual salary and
      under-deducts;
    * a salary revision mid-year and a one-off bonus are single events, and
      projecting them across the whole year over-deducts for the remainder.

    Because the projection is rebuilt from income *so far* every month, a
    revision or bonus self-corrects in the following period instead of
    compounding a permanent error for the rest of the year.

    ``current_month_pay`` must be the *recurring* monthly figure and must exclude
    one-off components -- a bonus, an arrears payment, a reimbursement. This is
    not a stylistic preference: it is multiplied by the months ahead, so a bonus
    of 200,000 in month 8 passed in as the run rate would be projected across the
    remaining months and over-deducted four times over. One-offs belong in
    ``income_to_date`` (where they are counted once, because they were genuinely
    received) or in ``scheduled_future_pay`` (where a known future amount is
    counted once as well). ``india.py`` documents the same requirement on the
    employee field.

    :param income_to_date: taxable income received in the FY up to and including
        the current month. One-off amounts belong here.
    :param current_month_pay: the recurring monthly pay component, excluding
        one-offs.
    :param months_remaining: months remaining in the FY, current one included.
    :param scheduled_future_pay: optional known total for the remaining months.
        When supplied it replaces the run-rate projection entirely.
    :returns: projected annual taxable income.
    """
    future_months = months_after_current(months_remaining)
    if scheduled_future_pay is not None:
        return float(income_to_date) + float(scheduled_future_pay)
    if future_months == 0:
        # Final month of the FY: there is nothing left to project.
        return float(income_to_date)
    return float(income_to_date) + float(current_month_pay) * future_months


def validate_slabs(slabs):
    """Check the configured slab table is contiguous and reaches the top.

    A table with a gap -- ``0-300k`` then ``900k-`` -- silently under-taxes
    everyone between the two bands, because the missing portion is not caught by
    any lookup: the lower slab's ceiling simply stops the walk early. Refusing
    the whole table is the only safe response, since one bad row would otherwise
    produce a plausible payslip with a wrong TDS figure.

    :raises ValueError: describing the specific defect.
    """
    if not slabs:
        raise ValueError("TDS: slab table is empty; refusing to guess a rate")

    ordered = sorted(
        slabs, key=lambda s: (s.get("from") if s.get("from") is not None else -1.0)
    )
    for previous, current in zip(ordered, ordered[1:]):
        prev_to = previous.get("to")
        cur_from = current.get("from")
        if prev_to is None:
            raise ValueError(
                "TDS: slab table has an open-ended band before "
                f"{cur_from}; bands must be contiguous and the open end last"
            )
        if float(prev_to) != float(cur_from):
            raise ValueError(
                f"TDS: slab table has a gap or overlap between {prev_to} and "
                f"{cur_from}; every band must start exactly where the last ended"
            )
    if ordered[-1].get("to") is not None:
        raise ValueError(
            "TDS: the top slab must be open-ended ('to': None) so high incomes "
            f"are still taxed; it currently stops at {ordered[-1].get('to')}"
        )
    return ordered


def tax_from_slabs(annual_taxable, slabs):
    """Apply marginal slabs to annual taxable income.

    Each slab is ``{"from": lo, "to": hi, "rate_pct": r}`` with ``None`` allowed
    for an open end. Tax is computed slab by slab on the portion of income that
    falls inside each slab -- this is a *marginal* calculation, not a flat rate
    applied to the whole income.

    Zero income is not an error: an employee below the first band owes nothing,
    and refusing that case would block a valid payroll.

    :returns: ``(total_tax, per_slab_breakdown)``. The breakdown is empty when
        income falls at or below the first band's floor.
    :raises ValueError: if the table is malformed (see ``validate_slabs``).
    """
    ordered = validate_slabs(slabs)

    if annual_taxable <= 0:
        return 0.0, []

    total = 0.0
    breakdown = []
    for slab in ordered:
        lo = slab.get("from")
        hi = slab.get("to")
        lower = 0.0 if lo is None else float(lo)
        if annual_taxable <= lower:
            continue
        upper = float("inf") if hi is None else float(hi)
        taxable_in_slab = min(annual_taxable, upper) - lower
        if taxable_in_slab <= 0:
            continue
        rate = float(slab.get("rate_pct", 0.0))
        amount = taxable_in_slab * rate / 100.0
        total += amount
        breakdown.append(
            {
                "from": lo,
                "to": hi,
                "rate_pct": rate,
                "taxable_in_slab": round(taxable_in_slab, 2),
                "tax": round(amount, 2),
            }
        )
    return total, breakdown


def apply_surcharge(tax_before_surcharge, annual_taxable, surcharge_bands):
    """Add surcharge for high incomes.

    ``surcharge_bands`` is a list of ``{"threshold": t, "pct": p}``. The highest
    matching band wins rather than stacking every band, because the statutory
    bands are alternative rates, not cumulative additions. Thresholds come from
    configuration.
    """
    if not surcharge_bands:
        return 0.0
    matched = None
    for band in surcharge_bands:
        if annual_taxable >= float(band.get("threshold", 0)):
            if matched is None or float(band.get("threshold", 0)) > float(
                matched.get("threshold", 0)
            ):
                matched = band
    if matched is None:
        return 0.0
    return tax_before_surcharge * float(matched.get("pct", 0.0)) / 100.0


def apply_cess(tax_after_surcharge, cess_pct):
    """Health and education cess, applied to the post-surcharge tax."""
    return tax_after_surcharge * float(cess_pct) / 100.0


def apply_marginal_relief(total_tax, annual_taxable, relief, tax_at_threshold=None):
    """Limit the tax on income above a threshold where the rate jumps sharply.

    Relief caps the *total* tax at:

        tax at the threshold  +  (income above the threshold x cap rate)

    It is not a per-slab adjustment and must not be implemented as one. Relief
    exists precisely because the jump between two adjacent bands is
    disproportionate; adjusting band by band would leave the higher rate applied
    to income above the threshold, which is the thing relief is meant to remove.
    The cap can therefore only be expressed against the whole liability.

    ``relief`` is ``{"threshold": t, "tax_at_threshold": x, "cap_rate_pct": r}``
    or ``None`` to disable. All three come from configuration.

    ``tax_at_threshold`` may be omitted by the caller, in which case it is
    recomputed from the slab table by ``compute_tds_arithmetic``.

    NOTE: the exact statutory formulation is a CA sign-off item. Specifically:
    whether ``cap_rate_pct`` is the threshold band's rate or the lower of the two
    adjacent rates, and whether relief is recomputed on the *reduced* income.
    See ``docs/compliance/CA-SIGNOFF-REQUEST.md``. This implementation is
    developer-derived from a general reading of the provision and must not be
    relied on until a professional confirms it.

    :returns: ``(total_tax, relief_amount)``.
    """
    if not relief:
        return total_tax, 0.0
    threshold = float(relief.get("threshold", 0) or 0)
    cap_rate = float(relief.get("cap_rate_pct", 0) or 0)
    if threshold <= 0 or annual_taxable <= threshold:
        return total_tax, 0.0

    base = relief.get("tax_at_threshold")
    if base is None:
        if tax_at_threshold is None:
            raise ValueError(
                "TDS: marginal relief needs either relief['tax_at_threshold'] or "
                "a computed tax_at_threshold; refusing to guess the cap"
            )
        base = tax_at_threshold
    cap = float(base) + (annual_taxable - threshold) * cap_rate / 100.0
    if total_tax <= cap:
        return total_tax, 0.0
    return cap, total_tax - cap


def apply_rebate(total_tax, annual_taxable, rebate):
    """Section 87A-style rebate, where eligibility is capped by income.

    ``rebate`` is ``{"max_income": i, "max_rebate": r, "rate_pct": p}`` or
    ``None``. Returns ``(rebated_tax, rebate_amount)``.

    NOTE: like marginal relief, the interaction between the rebate ceiling, the
    marginal-relief cap and the order in which they apply is a CA sign-off item.
    A lower marginal-relief cap applied before the rebate can produce a
    different liability than the reverse order, and the statute settles that
    question. This implementation caps first, then rebates. Developer-derived.
    """
    if not rebate:
        return total_tax, 0.0
    max_income = float(rebate.get("max_income", 0) or 0)
    if max_income and annual_taxable > max_income:
        return total_tax, 0.0
    rate = float(rebate.get("rate_pct", 100.0))
    amount = total_tax * rate / 100.0
    ceiling = rebate.get("max_rebate")
    if ceiling is not None:
        amount = min(amount, float(ceiling))
    return max(total_tax - amount, 0.0), amount


def split_tds_for_period(annual_liability, ytd_deducted, months_remaining):
    """Spread the year's remaining liability over the months that remain.

    ``annual_liability`` is the full-year tax computed from the projection.
    ``ytd_deducted`` is what has already been withheld earlier in the FY.

    The balance is divided by ``months_remaining`` -- which includes the
    current month -- so the employee finishes the year having paid the correct
    total without a year-end balancing entry. In the final month the divisor is
    1 and the employee pays the entire outstanding balance, which is where a
    shortfall becomes visible instead of being spread silently.

    :returns: ``(recoverable, non_recoverable)``. Over-deduction in an earlier
        month shows up as ``non_recoverable`` (to be reflected in the next
        salary) rather than being quietly ignored.
    """
    balance = float(annual_liability) - float(ytd_deducted)
    if balance < 0:
        return 0.0, round(-balance, 2)
    divisor = max(int(months_remaining), 1)
    return round(balance / divisor, 2), 0.0


def compute_tds_arithmetic(
    income_to_date,
    current_month_pay,
    months_elapsed,
    months_remaining,
    ytd_deducted,
    annual_deduction,
    slabs,
    cess_pct=0.0,
    surcharge_bands=None,
    relief=None,
    rebate=None,
    scheduled_future_pay=None,
    pay_basis="unspecified",
):
    """Full projection-to-deduction pipeline for one employee in one period.

    Callers that need the intermediate values for a payslip detail line should
    read them from the returned ``detail`` dict rather than recomputing.

    :param pay_basis: where ``current_month_pay`` came from -- ``explicit-field``,
        ``contract-wage`` or ``ytd-average``. Recorded in ``detail`` because the
        last of those includes one-off components and is therefore a
        best-effort figure rather than a recurring one.
    :returns: ``(recoverable, non_recoverable, detail)``.
    """
    projected = project_annual_income(
        income_to_date,
        current_month_pay,
        months_remaining,
        scheduled_future_pay=scheduled_future_pay,
    )
    annual_taxable = max(projected - float(annual_deduction or 0.0), 0.0)

    base_tax, breakdown = tax_from_slabs(annual_taxable, slabs)
    surcharge = apply_surcharge(base_tax, annual_taxable, surcharge_bands or [])
    after_surcharge = base_tax + surcharge
    cess = apply_cess(after_surcharge, cess_pct)
    after_cess = after_surcharge + cess

    # Marginal relief caps the *total*, so the cap is measured against the whole
    # liability. The threshold's own tax is needed to express that cap, so it is
    # recomputed from the same slab table rather than hardcoded.
    relief_threshold = float((relief or {}).get("threshold", 0) or 0)
    tax_at_threshold = 0.0
    if relief and relief_threshold > 0:
        tax_at_threshold, _ = tax_from_slabs(relief_threshold, slabs)

    capped, relief_amount = apply_marginal_relief(
        after_cess,
        annual_taxable,
        relief,
        tax_at_threshold=tax_at_threshold,
    )
    rebated, rebate_amount = apply_rebate(capped, annual_taxable, rebate)

    recoverable, non_recoverable = split_tds_for_period(
        rebated, ytd_deducted, months_remaining
    )

    detail = {
        "months_elapsed": months_elapsed,
        "months_remaining": months_remaining,
        "income_to_date": round(float(income_to_date), 2),
        "current_month_pay": round(float(current_month_pay), 2),
        "projected_annual_income": round(projected, 2),
        "annual_deduction_applied": round(float(annual_deduction or 0.0), 2),
        "annual_taxable": round(annual_taxable, 2),
        "slab_breakdown": breakdown,
        "base_tax": round(base_tax, 2),
        "surcharge": round(surcharge, 2),
        "cess_pct": float(cess_pct),
        "cess": round(cess, 2),
        "after_cess": round(after_cess, 2),
        "marginal_relief_applied": round(relief_amount, 2),
        "rebate_applied": round(rebate_amount, 2),
        "annual_liability": round(rebated, 2),
        "ytd_deducted_before": round(float(ytd_deducted), 2),
        "pay_basis": pay_basis,
        "method": "fy-so-far-plus-remaining-months",
        "relief_and_rebate_derived": True,
    }
    return recoverable, non_recoverable, detail