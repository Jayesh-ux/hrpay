"""Provident fund, ESI and Professional Tax arithmetic -- pure Python, no Odoo.

Why these are plain functions
----------------------------
The previous implementations lived inside ``india.py`` as methods on an
``AbstractModel``. They could only run inside Odoo, so on a machine without Docker
they had **zero** test coverage, and reviewing them by reading found defects in
every one (each is named at its function below). TDS had the same problem, and it
took two silently wrong tax numbers shipping before that was noticed.

Every function here takes and returns plain values. ``india.py`` is the only
caller: it reads configuration and translates refusals into ``UserError``. The
standalone tests import *this* module, so they exercise the code payroll runs
rather than a mirror of it.

No statutory value is hardcoded
-------------------------------
Rates, ceilings, bands and thresholds are all arguments, and no example schedule
in this file carries a real figure. A missing argument raises ``ValueError``
instead of defaulting to zero. A silent zero in a statutory deduction is the worst
outcome available: nothing errors, the payslip looks normal, and the employee
discovers it and disputes it.

Two figures that are deliberately *not* parameters, because they are arithmetic
rather than law, appear below: ``MONTHS_IN_FY`` and ``DAYS_IN_YEAR``.

The distinction this module exists to enforce: **an unconfigured statutory
parameter is an unanswered question, and an assumption is a wrong answer that
nobody can see.**
"""

MONTHS_IN_FY = 12
DAYS_IN_YEAR = 365


def _require(value, name):
    """Return ``value`` as a float, refusing a missing one."""
    if value is None:
        raise ValueError(
            f"{name} is not configured; refusing to substitute zero for a "
            f"statutory parameter"
        )
    return float(value)


# ─── Provident fund ───────────────────────────────────────────────────────────


def pf_base_and_ceiling(wages, wage_ceiling):
    """Apply the monthly PF wage ceiling.

    The ceiling is on the **wage**, not on the contribution, and it is inclusive:
    wages exactly at the ceiling are fully contributable. An employee one rupee
    above it contributes on the ceiling, not on their wage -- which is why the
    ``capped`` flag is returned rather than just the number, because the
    employee's PF on their actual salary is then not what the rate suggests.

    A negative wage (a credit note or negative adjustment) contributes by
    magnitude: an inverted ceiling bound would otherwise pay a deduction that
    increases with the employee's salary.
    """
    gross = abs(float(wages or 0.0))
    ceiling = _require(wage_ceiling, "IN.PF.WAGE_CEILING")
    if ceiling <= 0:
        raise ValueError("IN.PF.WAGE_CEILING must be positive")
    return min(gross, ceiling), gross > ceiling


def compute_pf(
    wages,
    employee_rate_pct,
    eps_rate_pct,
    wage_ceiling,
    employer_rate_pct=None,
    employer_eps_rate_pct=None,
    eps_monthly_cap=None,
    eps_annual_ceiling=None,
    eps_ytd_before=None,
    voluntary=None,
):
    """Split a month's PF into EPS and EPF for employee and employer.

    :param employee_rate_pct: the employee's total PF rate, EPS included.
    :param eps_rate_pct: the EPS portion of that rate.
    :param wage_ceiling: monthly ceiling on contributable wages.
    :param employer_rate_pct: the employer's total PF rate. **Required, not
        defaulted.** The previous implementation set the employer's contribution
        to the employee's rate by writing the same expression twice, which reads
        as a deliberate finding rather than an assumption. It is a statutory
        question and it is in the CA request.
    :param employer_eps_rate_pct: the employer's EPS rate, same reasoning.
    :param eps_monthly_cap: cap on the EPS contribution for one month, if any.
    :param eps_annual_ceiling: cap on EPS for the **financial year**, if any. When
        given, ``eps_ytd_before`` is required: a ceiling cannot be applied to a
        year without knowing where the year has got to.
    :param eps_ytd_before: EPS already contributed earlier in this financial
        year. The previous implementation documented that it could not cap EPS
        correctly without a year-to-date figure, then never read one, so an
        employee who crossed the annual ceiling kept contributing EPS for the
        rest of the year. Supplying ``eps_annual_ceiling`` with a silent zero is
        how that defect returns, so ``None`` is refused and ``0.0`` must be
        passed on purpose.
    :param voluntary: ``{"rate_pct": r, "cap": c, "counted_in_employee": bool,
        "counted_in_employer": bool}``. The flags are required because whether the
        employer matches a voluntary contribution is contractual, not statutory.
        The previous implementation added the voluntary amount to the **employer**
        total unconditionally, which had the employer paying an employee's chosen
        extra contribution.
    :returns: dict of contributions rounded to two places, plus the flags a
        reviewer needs in order to see which bounds bound.
    :raises ValueError: on a missing or unsound parameter.
    """
    employee_rate = _require(employee_rate_pct, "IN.PF.EMPLOYEE_RATE")
    eps_rate = _require(eps_rate_pct, "IN.PF.EPS_RATE")
    employer_rate = _require(employer_rate_pct, "IN.PF.EMPLOYER_RATE")
    employer_eps_rate = _require(employer_eps_rate_pct, "IN.PF.EMPLOYER_EPS_RATE")

    if employee_rate < 0 or eps_rate < 0 or employer_rate < 0:
        raise ValueError("PF rates cannot be negative")
    if eps_rate > employee_rate:
        raise ValueError(
            f"IN.PF.EPS_RATE ({eps_rate}%) exceeds IN.PF.EMPLOYEE_RATE "
            f"({employee_rate}%); the EPS share is part of the total rate"
        )
    if employer_eps_rate > employer_rate:
        raise ValueError(
            f"IN.PF.EMPLOYER_EPS_RATE ({employer_eps_rate}%) exceeds "
            f"IN.PF.EMPLOYER_RATE ({employer_rate}%)"
        )

    base, capped = pf_base_and_ceiling(wages, wage_ceiling)

    base_employee = base * (employee_rate / 100.0)
    base_employer = base * (employer_rate / 100.0)

    eps_employee = base * (eps_rate / 100.0)
    eps_employer = base * (employer_eps_rate / 100.0)

    flags = {
        "wage_ceiling_applied": capped,
        "eps_monthly_cap_applied": False,
        "eps_annual_ceiling_applied": False,
    }

    if eps_monthly_cap is not None:
        cap = float(eps_monthly_cap)
        if cap < 0:
            raise ValueError("IN.PF.EPS_MONTHLY_CAP cannot be negative")
        if eps_employee > cap:
            eps_employee = cap
            flags["eps_monthly_cap_applied"] = True
        if eps_employer > cap:
            eps_employer = cap

    if eps_annual_ceiling is not None:
        annual_cap = _require(eps_annual_ceiling, "IN.PF.EPS_ANNUAL_CEILING")
        already = _require(eps_ytd_before, "IN.PF.EPS_ANNUAL_CEILING year-to-date")
        if already < 0:
            raise ValueError("EPS year-to-date cannot be negative")
        headroom = annual_cap - already
        if headroom <= 0:
            # The year-to-date figure already reaches the ceiling. EPS stops
            # entirely and the whole contribution falls to EPF.
            eps_employee = 0.0
            eps_employer = 0.0
            flags["eps_annual_ceiling_applied"] = True
        else:
            if eps_employee > headroom:
                eps_employee = headroom
                flags["eps_annual_ceiling_applied"] = True
            if eps_employer > headroom:
                eps_employer = headroom
    elif eps_ytd_before is not None:
        raise ValueError(
            "eps_ytd_before was supplied without eps_annual_ceiling; an EPS "
            "year-to-date figure is meaningless without the ceiling it is "
            "measured against. Configure IN.PF.EPS_ANNUAL_CEILING, or pass no "
            "year-to-date figure at all."
        )

    # Voluntary PF sits outside the EPS/EPF split and is allocated by config.
    voluntary_amount = 0.0
    to_employee = 0.0
    to_employer = 0.0
    if voluntary:
        rate = _require(voluntary.get("rate_pct"), "IN.PF.VOLUNTARY default_rate_pct")
        if rate < 0:
            raise ValueError("voluntary PF rate cannot be negative")
        if "counted_in_employee" not in voluntary or "counted_in_employer" not in voluntary:
            raise ValueError(
                "IN.PF.VOLUNTARY must state counted_in_employee and "
                "counted_in_employer; whether the employer matches the employee's "
                "voluntary contribution is contractual, so it is configured "
                "rather than assumed"
            )
        voluntary_amount = base * (rate / 100.0)
        cap = voluntary.get("cap")
        if cap is not None:
            if float(cap) < 0:
                raise ValueError("voluntary PF cap cannot be negative")
            voluntary_amount = min(voluntary_amount, float(cap))
        to_employee = voluntary_amount if voluntary["counted_in_employee"] else 0.0
        to_employer = voluntary_amount if voluntary["counted_in_employer"] else 0.0

    total_employee = base_employee + to_employee
    total_employer = base_employer + to_employer

    epf_employee = base_employee - eps_employee
    epf_employer = base_employer - eps_employer

    return {
        "pf_wages": round(base, 2),
        "pf_capped": capped,
        "wage_ceiling_applied": float(_require(wage_ceiling, "IN.PF.WAGE_CEILING")),
        "pf_employee": round(total_employee, 2),
        "pf_employer": round(total_employer, 2),
        "pf_eps_employee": round(eps_employee, 2),
        "pf_eps_employer": round(eps_employer, 2),
        "pf_epf_employee": round(epf_employee, 2),
        "pf_epf_employer": round(epf_employer, 2),
        "pf_voluntary": round(voluntary_amount, 2),
        "pf_voluntary_employee": round(to_employee, 2),
        "pf_voluntary_employer": round(to_employer, 2),
        "eps_monthly_cap_applied": flags["eps_monthly_cap_applied"],
        "eps_annual_ceiling_applied": flags["eps_annual_ceiling_applied"],
    }


# ─── Employees' State Insurance ───────────────────────────────────────────────


def validate_esi_schedule(schedule):
    """Check an ESI schedule is a coherent, gap-free band table.

    ``schedule`` is a mapping, so the reading travels with the bands and cannot
    be separated from them::

        {"mode": "band_amount",       # or "rate"
         "coverage_ceiling": 25000,   # above this ESI does not apply
         "bands": [{"up_to": ..., "employee": ..., "employer": ...}, ...]}

    ``mode`` is mandatory. The previous implementation applied a flat percentage
    of wages unconditionally, and a band *amount* was never representable, so the
    question of which reading is right could not even be asked of the code. See
    CA request section 4.1.
    """
    if not schedule:
        raise ValueError(
            "IN.ESI.CONTRIBUTION_SCHEDULE is not configured; refusing to guess "
            "between a band amount and a percentage of wages (CA request 4.1)"
        )
    if not isinstance(schedule, dict):
        raise ValueError(
            "the ESI schedule must be a mapping with 'mode', 'coverage_ceiling' "
            "and 'bands'; a bare list of bands cannot say which statutory reading "
            "it represents"
        )

    mode = schedule.get("mode")
    if mode not in ("band_amount", "rate"):
        raise ValueError(
            f"the ESI schedule declares no usable mode ({mode!r}); set 'mode' to "
            "'band_amount' or 'rate' so the statutory reading is explicit"
        )
    if mode == "rate" and not schedule.get("provisional"):
        raise ValueError(
            "the ESI schedule is a percentage of wages, which we do not believe "
            "is correct. Mark it provisional in config and have the CA confirm "
            "CA request 4.1 before relying on it"
        )

    bands = schedule.get("bands")
    if not bands:
        raise ValueError("the ESI schedule has no bands")

    ceiling = schedule.get("coverage_ceiling")
    if ceiling is None:
        raise ValueError(
            "the ESI schedule needs an explicit 'coverage_ceiling'; without it, "
            "a wages figure above the last band is indistinguishable from a "
            "missing table and is silently exempt"
        )

    ordered = sorted(bands, key=lambda b: float(b.get("up_to") or 0.0))
    previous = 0.0
    for band in ordered:
        upper = band.get("up_to")
        if upper is None:
            raise ValueError(
                "an ESI band has no upper limit; coverage ends at "
                f"{ceiling:,.2f}, so every band needs one"
            )
        upper = float(upper)
        if upper <= previous:
            raise ValueError(
                f"ESI bands overlap or repeat at {upper:,.2f}"
            )
        if upper > previous:
            previous = upper
    if abs(previous - float(ceiling)) > 0.01:
        raise ValueError(
            f"the ESI bands stop at {previous:,.2f} but coverage_ceiling is "
            f"{float(ceiling):,.2f}; wages in between would silently escape ESI"
        )
    return ceiling


def compute_esi(wages, schedule):
    """ESI contribution for one month.

    :returns: dict including ``esi_applicable`` and, above the ceiling,
        ``above_coverage_ceiling`` so the exemption is visible rather than
        implied by two zeros.
    """
    ceiling = validate_esi_schedule(schedule)
    bands = sorted(schedule["bands"], key=lambda b: float(b["up_to"]))
    mode = schedule["mode"]

    gross = abs(float(wages or 0.0))
    base = {
        "esi_wages": round(gross, 2),
        "esi_mode": mode + ("-provisional" if schedule.get("provisional") else ""),
    }

    if gross > ceiling:
        return {
            **base,
            "esi_applicable": False,
            "esi_employee": 0.0,
            "esi_employer": 0.0,
            "esi_band_up_to": ceiling,
            "above_coverage_ceiling": True,
        }

    for band in bands:
        if gross <= float(band["up_to"]):
            if mode == "band_amount":
                ee = float(band.get("employee", 0.0))
                er = float(band.get("employer", 0.0))
            else:
                ee = gross * float(band.get("employee_rate_pct", 0.0)) / 100.0
                er = gross * float(band.get("employer_rate_pct", 0.0)) / 100.0
            return {
                **base,
                "esi_applicable": bool(ee or er),
                "esi_employee": round(ee, 2),
                "esi_employer": round(er, 2),
                "esi_band_up_to": float(band["up_to"]),
            }

    # Unreachable while validate_esi_schedule holds, but a silent zero here would
    # be indistinguishable from a genuine exemption, so it refuses.
    raise ValueError(
        f"no ESI band covers wages {gross:,.2f} within coverage_ceiling "
        f"{ceiling:,.2f}; the schedule is not contiguous"
    )


# ─── Professional Tax ─────────────────────────────────────────────────────────


def validate_pt_slabs(slabs):
    """Check the PT band table covers every income, with no gap.

    Professional Tax tables are per State and a gap in one produces a zero nobody
    notices, so the table is validated the way the TDS slab table is: contiguous
    from zero, and the top band open-ended so a high salary is still taxed.
    """
    if not slabs:
        raise ValueError(
            "IN.PT.SLABS is not configured for this State. States that levy no PT "
            "must be configured with an explicit zero band rather than left empty, "
            "because the previous behaviour was a silent zero that looked like a "
            "correct deduction."
        )

    ordered = sorted(
        slabs, key=lambda s: (float(s["from"]) if s.get("from") is not None else -1.0)
    )
    if ordered[0].get("from") not in (0, 0.0):
        raise ValueError(
            f"the PT slab table starts at {ordered[0].get('from')}; income below "
            "that would silently escape PT entirely"
        )
    for previous, current in zip(ordered, ordered[1:]):
        prev_to = previous.get("to")
        if prev_to is None:
            raise ValueError("the PT slab table has an open-ended band before the top")
        if float(prev_to) != float(current.get("from", -1)):
            raise ValueError(
                f"gap or overlap in the PT slab table between {prev_to} and "
                f"{current.get('from')}"
            )
    if ordered[-1].get("to") is not None:
        raise ValueError(
            "the top PT band must be open-ended so a high salary is still taxed; "
            f"it stops at {ordered[-1].get('to')}"
        )
    return ordered


def compute_pt(monthly_income, slabs, ytd_pt=0.0, annual_cap=None,
               boundary="inclusive"):
    """Professional Tax for one month, with the annual cap applied.

    :param boundary: whether a band's upper figure is **inclusive** of it
        (``inclusive``) or exclusive (``exclusive``). This is a genuine ambiguity
        at every band edge and is listed in the CA request; it is a parameter here
        so a correction is a config change, not a code change. The previous
        implementation tested ``amount <= hi`` and documented nothing, so the
        answer at every band edge was undocumented behaviour.
    :param annual_cap: the constitutional per-year cap, if any. ``None`` and
        ``0`` are different: ``None`` means unconfigured, ``0`` means nothing may
        ever be deducted. The previous implementation used ``if annual_cap:``, so
        a configured zero was treated as absent.
    :raises ValueError: on a malformed table or an unmatchable income.
    """
    if boundary not in ("inclusive", "exclusive"):
        raise ValueError(
            f"unknown PT boundary rule {boundary!r}; the statute settles this and "
            "it is a CA request item, not a default"
        )
    ordered = validate_pt_slabs(slabs)

    amount = abs(float(monthly_income or 0.0))
    matched = None
    for slab in ordered:
        lo = slab.get("from")
        hi = slab.get("to")
        if lo is not None and amount < float(lo):
            continue
        if hi is None:
            matched = slab
            break
        if boundary == "inclusive":
            if amount <= float(hi):
                matched = slab
                break
        elif amount < float(hi):
            matched = slab
            break

    if matched is None:
        raise ValueError(
            f"no PT band matches monthly income {amount:,.2f}; the band table is "
            "incomplete. A zero here is a silent non-deduction, so it is refused."
        )

    pt_employee = float(matched.get("employee", 0.0))
    pt_employer = float(matched.get("employer", 0.0))

    note = None
    if annual_cap is not None:
        cap = float(annual_cap)
        if cap < 0:
            raise ValueError("IN.PT.ANNUAL_CAP cannot be negative")
        already = float(ytd_pt or 0.0)
        if already >= cap:
            pt_employee = 0.0
            note = "annual cap already reached"
        elif already + pt_employee > cap:
            pt_employee = cap - already
            note = "annual cap reached this month; part-month amount"

    return {
        "pt_employee": round(pt_employee, 2),
        "pt_employer": round(pt_employer, 2),
        "matched_slab": matched,
        "annual_cap_note": note,
    }
