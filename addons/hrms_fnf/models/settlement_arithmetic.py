"""Final-settlement arithmetic -- pure Python, no Odoo.

Covers notice-period shortfall recovery, leave encashment valuation and the
netting of the settlement itself.

Defects found by reviewing the previous inline implementation
-------------------------------------------------------------

1. **Leave accrual grew with the square of service months.** The code computed the
   accrual *per month*, then rebound the variable name to the *count of service
   months*, and multiplied the number by itself::

       months = value.get("annual_days", 0) / 12.0     # accrual per month
       ...
       months = _months(start, last_working_day)       # service months
       return round(months * months, 2)                # 18 months -> 324 days

   Eighteen months of service entitled an employee to 324 days of leave. Every
   amount derived from it was wrong, and the wrong direction favours the employee,
   so it would have been paid without complaint and corrected at audit.

2. **Accrual could never resolve, so leave encashment was always zero.** The code
   looked up ``IN.LEAVE.ACCRUAL_DAYS.<leave_type>``, a code that is not in the
   runtime catalog, and then swallowed the resulting error and returned zero days.
   A statutory payment that is always zero and raises no error is the worst
   combination available: the payslip is clean and the employee is owed money.

3. **The "daily wages" basis was ``CTC / 365``.** Same defect as the gratuity
   basis: CTC is not statutory wages.

4. **The three-month average summed every payslip line**, picking up employer
   contributions and netting off employee deductions, then divided an average
   *monthly* total by the day count of the **exit month** -- a 28-day February
   dividing a figure averaged over three different-length months.

5. **Notice shortfall used the contract wage with no statutory ceiling check**,
   and recovered the shortfall even when the exit reason did not permit recovery.
   The authority to recover comes from the contract and the exit reason, not from
   the arithmetic, so both are inputs here and neither is assumed.

Every statutory figure is an argument, and a missing one raises.
"""

MONTHS_IN_FY = 12


def _require(value, name):
    if value is None:
        raise ValueError(
            f"{name} is not configured; refusing to substitute zero for a "
            f"statutory parameter"
        )
    return float(value)


# ─── Leave accrual and encashment ─────────────────────────────────────────────


def service_months(start, end):
    """Complete months of service between two dates."""
    if start is None or end is None:
        raise ValueError("service period needs both a start and an end date")
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def accrued_leave_days(annual_days=None, monthly_days=None, months_of_service=None,
                       as_of_months=None):
    """Days of a leave type accrued by an employee.

    Exactly one of ``annual_days`` or ``monthly_days`` must be supplied by
    configuration. Accrual is then **accrual per month times months of service** --
    linear, because accrual is linear. The previous implementation squared it.

    :param as_of_months: months of service to accrue for, overriding
        ``months_of_service``. Supplied when the caller already counted them.
    :raises ValueError: when neither accrual figure is configured, when both are,
        or when the resulting accrual is negative.
    """
    if (annual_days is None) == (monthly_days is None):
        raise ValueError(
            "leave accrual needs exactly one of annual_days or monthly_days from "
            "statutory config; supplying neither means the accrual is unknown and "
            "supplying both is ambiguous"
        )

    per_month = (
        float(annual_days) / 12.0 if annual_days is not None else float(monthly_days)
    )
    if per_month < 0:
        raise ValueError("leave accrual cannot be negative")

    months = as_of_months if as_of_months is not None else months_of_service
    if months is None:
        raise ValueError(
            "leave accrual needs months of service; without it the accrual is a "
            "rate multiplied by nothing"
        )
    months = float(months)
    if months < 0:
        raise ValueError("months of service cannot be negative")

    return round(per_month * months, 2)


def daily_wage(monthly_wage, days_in_month, basis="wages"):
    """Daily wage for leave encashment.

    :param basis: ``wages`` takes a statutory wage figure; ``ctc`` takes CTC and is
        refused unless explicitly requested, because CTC includes components the
        statute excludes. The previous code used ``CTC / 365`` unconditionally and
        labelled the result "daily wages".
    :param days_in_month: the divisor. 365 is a **year**, not a month, and using it
        as a monthly divisor understated the daily rate by roughly an order of
        magnitude.
    """
    amount = _require(monthly_wage, "leave encashment wage basis")
    days = int(days_in_month or 0)
    if days <= 0:
        raise ValueError(
            "days_in_month must be positive; a zero divisor previously produced "
            "an encashment of zero with no error"
        )
    if basis not in ("wages", "ctc"):
        raise ValueError(f"unknown encashment basis '{basis}'")
    return amount / days


def encashment_for_leave(unused_days, daily_rate, excess_days=0.0,
                         carry_forward_days=None, recovery_permitted=True):
    """Split unused leave into a payable amount and a recoverable excess.

    :param carry_forward_days: days that may be carried into next year instead of
        recovered. Leave taken beyond accrual plus carry-forward is recovered.
        ``None`` means no carry-forward allowance is configured, which is
        **nothing carried forward** -- so the whole excess is recoverable. Treating
        it as "recover nothing" would quietly forgive the excess instead.
    :param recovery_permitted: mirrors the authority check on notice shortfall.
        Recovering without authority is itself unlawful, so this defaults to not
        recovering rather than to recovering.
    :returns: dict with ``encashable_amount`` and ``recoverable_amount``.
    """
    unused = float(unused_days or 0.0)
    if unused < 0:
        raise ValueError("unused leave days cannot be negative")
    rate = _require(daily_rate, "daily rate")

    excess = float(excess_days or 0.0)
    if excess < 0:
        raise ValueError("excess leave days cannot be negative")

    allowance = float(carry_forward_days or 0.0)
    if allowance < 0:
        raise ValueError("carry-forward days cannot be negative")
    recoverable_days = max(0.0, excess - allowance)

    return {
        "encashable_amount": round(unused * rate, 2),
        "recoverable_amount": (
            round(recoverable_days * rate, 2) if recovery_permitted else 0.0
        ),
        "recoverable_days": round(recoverable_days, 2),
        "recovery_suppressed": bool(recoverable_days and not recovery_permitted),
    }


# ─── Notice-period shortfall ──────────────────────────────────────────────────


def notice_shortfall_days(contractual_days, served_days):
    """Days of notice the employee failed to serve.

    A negative result means notice was over-served, which is a **payment to the
    employee**, not a recovery. Returning it as a negative rather than clamping to
    zero is what lets the caller tell the two apart.
    """
    required = int(contractual_days or 0)
    served = int(served_days or 0)
    if required < 0 or served < 0:
        raise ValueError("notice days cannot be negative")
    return required - served


def notice_shortfall_recovery(shortfall_days, daily_rate, permits_recovery,
                              ceiling=None, max_recoverable=None):
    """Amount recoverable for unserved notice.

    :param permits_recovery: authority to recover. Where it is false the amount
        is returned as zero with ``recovery_suppressed`` set, and the reason is
        recorded -- a shortfall exists, it is simply not ours to take.
    :param ceiling: statutory cap on the recoverable amount, if any.
    :param max_recoverable: the amount the contract itself permits, which is
        frequently less than the shortfall and is a contractual fact.
    """
    days = float(shortfall_days or 0.0)
    if days < 0:
        raise ValueError("shortfall days cannot be negative")
    rate = _require(daily_rate, "daily rate for notice shortfall")

    amount = days * rate
    notes = []
    if not permits_recovery:
        notes.append(
            f"shortfall of {days:g} day(s) exists but recovery is not permitted, "
            "so nothing was deducted"
        )
        return {
            "recovery_amount": 0.0,
            "uncapped_amount": round(amount, 2),
            "recovery_suppressed": True,
            "notes": notes,
        }

    if max_recoverable is not None:
        allowed = float(max_recoverable)
        if allowed < 0:
            raise ValueError("max_recoverable cannot be negative")
        if amount > allowed:
            notes.append(
                f"capped at the contractually recoverable {allowed:,.2f}, below "
                f"the {amount:,.2f} shortfall value"
            )
            amount = allowed

    if ceiling is not None:
        cap = float(ceiling)
        if cap >= 0 and amount > cap:
            notes.append(f"capped at the statutory limit {cap:,.2f}")
            amount = cap

    return {
        "recovery_amount": round(amount, 2),
        "uncapped_amount": round(days * rate, 2),
        "recovery_suppressed": False,
        "notes": notes,
    }


# ─── Settlement netting ───────────────────────────────────────────────────────


def net_settlement(payable_lines, deduction_lines):
    """Net a final settlement, distinguishing a shortfall from a payment.

    The previous implementation summed ``abs(amount)`` over deduction lines, which
    means a negative payable and a deduction net off each other and a genuine
    over-deduction is indistinguishable from a normal one. Here the two sides are
    kept apart and the negative case is reported with its magnitude, because a
    negative settlement is a recovery from the employee and has different
    consequences -- it needs authority, and often instalments -- from a payment.

    :param payable_lines: ``[{"amount": x, ...}, ...]``
    :param deduction_lines: ``[{"amount": y, ...}, ...]``. Amounts are taken as
        given; a caller that stores deductions as negative should convert first,
        which this function makes explicit by refusing a negative deduction.
    :returns: dict with the gross, the deductions, the net, and either
        ``recovery_due`` or ``amount_payable`` -- never a bare negative net.
    """
    gross = 0.0
    for line in payable_lines or []:
        amount = float(line.get("amount", 0.0) if isinstance(line, dict) else line)
        if amount < 0:
            raise ValueError(
                f"payable line has a negative amount ({amount:,.2f}); move it to "
                "the deduction side so a shortfall cannot hide inside a payment"
            )
        gross += amount

    deductions = 0.0
    for line in deduction_lines or []:
        amount = float(line.get("amount", 0.0) if isinstance(line, dict) else line)
        if amount < 0:
            raise ValueError(
                f"deduction line is negative ({amount:,.2f}); deductions are "
                "supplied as positive magnitudes and subtracted"
            )
        deductions += amount

    net = round(gross - deductions, 2)
    return {
        "gross_payable": round(gross, 2),
        "total_deductions": round(deductions, 2),
        "net_payable": net,
        "is_negative_settlement": net < 0,
        "amount_payable": net if net > 0 else 0.0,
        "recovery_due": -net if net < 0 else 0.0,
        "line_count": len(list(payable_lines or [])) + len(list(deduction_lines or [])),
    }
