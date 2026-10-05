"""Gratuity arithmetic -- pure Python, no Odoo.

Defects found by reviewing the previous inline implementation
-------------------------------------------------------------

1. **The "part thereof in excess of six months" rule counted exactly six months as
   a full year.** The statutory phrase is *in excess of*, so a remainder of exactly
   six months is not a part exceeding six months. An employee with 5 years and
   exactly 6 months was paid 6 units of gratuity instead of 5. Whether the boundary
   is inclusive is a genuine ambiguity -- some readings treat six months as
   sufficient -- so it is a parameter here and a question in the CA request. The
   default is the literal reading.

2. **The wage basis fell back to ``CTC / 12``.** Gratuity is payable on last-drawn
   *wages* as the law defines them. CTC normally includes employer PF, a gratuity
   accrual and insurance, none of which are wage, so ``CTC / 12`` overstates the
   basis and therefore overstates the employee's gratuity. Worse, when a payslip
   was found the basis was **the sum of every payslip line**, which picks up
   employer contributions and nets off employee deductions.

   Rather than pick a different wrong figure, ``wage_basis_from_payslip_gross``
   takes an explicit gross earnings figure supplied by the caller. When no payslip
   exists the caller has nothing valid to pass, so this module refuses; the engine
   decides what to do about that, and refusing is the point.

3. The interest payable for late payment, which the register claims, was never
   computed. ``gratuity_interest`` exists here and is not yet called, because the
   rate is not known. It raises rather than defaulting to zero.

Nothing here decides policy. Every statutory figure is an argument.
"""


def _require(value, name):
    if value is None:
        raise ValueError(
            f"{name} is not configured; refusing to substitute zero for a "
            f"statutory parameter"
        )
    return float(value)


def service_months(start, end, inclusive_end=False):
    """Complete months between two dates.

    :param inclusive_end: treat the end date as fully served. A fixed-term
        contract obliges service to the last day of its term, so a contract from
        1 January to 31 December is twelve months, not eleven. Without this a
        completed one-year fixed term fails a one-year pro-rata threshold.
    """
    if start is None or end is None:
        raise ValueError("service period needs both a start and an end date")
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if inclusive_end:
        # Adding a day to a month end lands in the following month, so the month
        # count includes the final month in full.
        if (end.day + 1) > _days_in_month(end):
            months += 1
        return months
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _days_in_month(day):
    from calendar import monthrange

    return monthrange(day.year, day.month)[1]


def countable_years(total_months, pro_rata=False, partial_threshold_months=6,
                    boundary="exclusive"):
    """Years of service that attract gratuity.

    :param pro_rata: for fixed-term employees every month counts proportionally.
    :param partial_threshold_months: the "in excess of" threshold, 6 by default.
    :param boundary: ``exclusive`` counts a remainder only when it **exceeds** the
        threshold -- the literal reading of the statute. ``inclusive`` counts a
        remainder equal to it. The previous implementation behaved as though
        ``inclusive`` while documenting ``exclusive``.

    :returns: ``(years, note)`` where the note explains which way it went, because
        a gratuity that differs from expectation is almost always this boundary.
    """
    months = int(total_months or 0)
    if months < 0:
        raise ValueError("total_months cannot be negative")
    if boundary not in ("exclusive", "inclusive"):
        raise ValueError(
            f"unknown boundary rule {boundary!r}; whether a remainder of exactly "
            "six months counts is a CA request item, not a default"
        )

    if pro_rata:
        return months / 12.0, "pro-rata: every month counted proportionally"

    full = months // 12
    remainder = months % 12
    threshold = int(partial_threshold_months or 0)

    if threshold <= 0:
        return float(full), f"no partial-year rule; {full} complete year(s)"

    if remainder > threshold:
        return float(full + 1), (
            f"remainder {remainder}m exceeds {threshold}m, counted as a full year"
        )
    if remainder == threshold and boundary == "inclusive":
        return float(full + 1), (
            f"remainder exactly {threshold}m, counted as a full year "
            f"(boundary: inclusive)"
        )
    if remainder == threshold:
        return float(full), (
            f"remainder exactly {threshold}m does not exceed {threshold}m, "
            f"not counted (boundary: exclusive)"
        )
    return float(full), (
        f"remainder {remainder}m does not exceed {threshold}m, not counted"
    )


def wage_basis_from_payslip_gross(gross_earnings):
    """Last-drawn wages for gratuity, from a caller-supplied gross figure.

    :raises ValueError: when there is no gross figure. An absent payslip is not
        grounds for substituting CTC or the contract wage, because both include
        components the statute excludes from "wages". The engine surfaces this to
        the user instead of quietly over-paying.
    """
    if gross_earnings is None:
        raise ValueError(
            "gratuity wage basis: no last-drawn wages available. Refusing to "
            "substitute CTC or the contract wage, because both include employer "
            "contributions that are not statutory 'wages'. Supply the gross "
            "earnings figure or resolve CA request section 2 (gratuity wage "
            "components) first."
        )
    value = float(gross_earnings)
    if value <= 0:
        raise ValueError(
            f"gratuity wage basis must be positive, got {value:,.2f}; a zero or "
            "negative basis produces a zero gratuity that looks valid"
        )
    return round(value, 2)


def compute_gratuity(wage_basis, days_per_year, countable_years_value,
                     wages_divisor, ceiling=None, decimal_places=2):
    """Gratuity payable, and the excess above any ceiling.

    :param wages_divisor: ``IN.GRATUITY.WAGES_DIVISOR``. The code exists in the
        catalog but its value is unvalidated, and the register notes that the
        divisor is for the Central Government to specify. A divisor is therefore
        required here rather than assumed, and the seed value is a claim to be
        confirmed, not a fact (CA request 2).
    :param ceiling: ``IN.GRATUITY.CEILING``, if any. ``None`` means "no ceiling
        configured", which is different from "a ceiling of zero".
    :returns: dict including ``excess_over_ceiling`` -- the amount **disallowed**,
        kept distinct from ``payable`` so neither can be mistaken for the other.
    """
    basis = _require(wage_basis, "gratuity wage basis")
    days = _require(days_per_year, "IN.GRATUITY.DAYS_PER_YEAR")
    divisor = _require(wages_divisor, "IN.GRATUITY.WAGES_DIVISOR")
    if divisor <= 0:
        raise ValueError("IN.GRATUITY.WAGES_DIVISOR must be positive")
    if days < 0:
        raise ValueError("IN.GRATUITY.DAYS_PER_YEAR cannot be negative")

    years = float(countable_years_value or 0.0)
    if years < 0:
        raise ValueError("countable years cannot be negative")

    daily_wage = basis / divisor
    amount = daily_wage * days * years

    payable = amount
    excess = 0.0
    ceiling_applied = False
    if ceiling is not None:
        cap = float(ceiling)
        if cap >= 0 and amount > cap:
            payable = cap
            excess = amount - cap
            ceiling_applied = True

    return {
        "daily_wage": round(daily_wage, decimal_places),
        "uncapped_amount": round(amount, decimal_places),
        "payable": round(payable, decimal_places),
        "excess_over_ceiling": round(excess, decimal_places),
        "ceiling_applied": ceiling_applied,
    }


def gratuity_interest(principal, days_late, rate_pct, compounding="simple"):
    """Interest on gratuity paid late.

    The register claims the Act provides for interest; the **rate is not known**,
    so this exists but is not called. It raises on a missing rate rather than
    returning zero, because a zero here reads as "no interest owed" on a payslip.

    :param days_late: whole days beyond the payment deadline.
    """
    amount = _require(principal, "gratuity principal")
    rate = _require(rate_pct, "gratuity interest rate")
    if rate <= 0:
        raise ValueError("interest rate must be positive to compute interest")
    days = int(days_late or 0)
    if days < 0:
        raise ValueError("days_late cannot be negative")

    if compounding == "simple":
        interest = amount * (rate / 100.0) * (days / 365.0)
    elif compounding == "compounded_annual":
        interest = amount * ((1 + rate / 100.0) ** (days / 365.0) - 1)
    else:
        raise ValueError(
            f"unknown compounding basis '{compounding}'; the statute settles "
            "this and it is a CA request item, not a default"
        )
    return round(interest, 2)
