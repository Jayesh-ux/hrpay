#!/usr/bin/env python3
"""Developer-derived checks of the contribution and gratuity arithmetic.

READ THIS BEFORE TRUSTING A PASSING RUN
=======================================

Every expected number here is **ours**, not a professional's. These tests prove
the code matches our reading of the rules. They do not prove the reading is right.

Every figure below is invented. No real employee data, and no real employer's
data, appears anywhere in this file.

What these tests *do* establish is that a set of defects found by reading the
inline implementations are gone, and cannot come back silently:

* ESI applied a flat percentage of wages, and could not represent a band *amount*
  at all, so the reading could not even be put to the code;
* the EPS **annual** ceiling could never stop EPS -- the code documented that it
  needed a year-to-date figure and then never read one;
* the employer PF rate was the employee's rate, written as the same expression
  twice, which reads as a finding rather than an assumption;
* the employer paid the employee's **voluntary** PF contribution;
* ``IN.PF.EPS_ANNUAL_CAP`` held a *monthly* figure, so the name and the value
  disagreed;
* gratuity counted a remainder of exactly six months as a full year, although the
  statute says *in excess of* six months;
* the gratuity wage basis fell back to ``CTC / 12``, and where a payslip was found
  summed *every* line, picking up employer contributions and netting off employee
  deductions;
* PT returned zero for a State with no table configured, and a band edge had
  undocumented inclusive behaviour.

Run with plain Python -- no pytest, no Odoo, no Docker:

    python3 tests/standalone/test_statutory_arithmetic_DEV.py
"""

import datetime
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))


def _load(addon, name):
    path = os.path.join(_REPO, "addons", addon, "models", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


contrib, _CONTRIB_PATH = _load("hrms_statutory", "contribution_arithmetic")
grat, _GRAT_PATH = _load("hrms_statutory", "gratuity_arithmetic")


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


# ─── Provident fund: the wage ceiling ─────────────────────────────────────────

PF = {
    "employee_rate_pct": 12.0,
    "eps_rate_pct": 8.33,
    "employer_rate_pct": 12.0,
    "employer_eps_rate_pct": 8.33,
    "wage_ceiling": 15000.0,
}


def test_pf_below_ceiling_contributes_on_full_wages():
    r = contrib.compute_pf(wages=10000.0, **PF)
    check("PF wages are the full wage", r["pf_wages"], 10000.0)
    check("employee PF at 12%", r["pf_employee"], 1200.0)
    check("EPS at 8.33%", r["pf_eps_employee"], 833.0)
    check("EPF is the remainder", r["pf_epf_employee"], 367.0)
    check("no ceiling flagged", r["pf_capped"], False)


def test_pf_exactly_at_ceiling_is_not_capped():
    """The ceiling is inclusive: wages equal to it are fully contributable."""
    r = contrib.compute_pf(wages=15000.0, **PF)
    check("PF wages at the ceiling", r["pf_wages"], 15000.0)
    check("ceiling not flagged as applied", r["pf_capped"], False)


def test_pf_one_rupee_above_ceiling_contributes_on_the_ceiling():
    r = contrib.compute_pf(wages=15000.01, **PF)
    check("basis stops at the ceiling", r["pf_wages"], 15000.0)
    check("ceiling flagged", r["pf_capped"], True)
    check("contribution is the ceiling's, not the wage's", r["pf_employee"], 1800.0)


def test_pf_far_above_ceiling_is_still_the_ceiling():
    r = contrib.compute_pf(wages=90000.0, **PF)
    check("basis", r["pf_wages"], 15000.0)
    check("employee PF", r["pf_employee"], 1800.0)


def test_pf_negative_wages_use_the_magnitude():
    """A credit note or a negative adjustment must not invert the ceiling."""
    r = contrib.compute_pf(wages=-20000.0, **PF)
    check("negative wages treated by magnitude", r["pf_wages"], 15000.0)
    check("and still capped", r["pf_capped"], True)


def test_pf_refuses_a_missing_ceiling():
    """A zero ceiling would look like 'contribute on nothing'."""
    kwargs = dict(PF)
    kwargs["wage_ceiling"] = None
    raises(lambda: contrib.compute_pf(wages=10000.0, **kwargs), "not configured")


def test_pf_refuses_eps_rate_above_total():
    kwargs = dict(PF, eps_rate_pct=40.0)
    raises(lambda: contrib.compute_pf(wages=10000.0, **kwargs))


def test_pf_refuses_an_unstated_employer_rate():
    """The defect: the employer's rate was the employee's, by duplicated code."""
    kwargs = {k: v for k, v in PF.items()
              if k not in ("employer_rate_pct", "employer_eps_rate_pct")}
    raises(lambda: contrib.compute_pf(wages=10000.0, **kwargs),
           "IN.PF.EMPLOYER_RATE")


def test_pf_employer_rate_may_differ_from_the_employee():
    """Statutory rates are not required to match; the code must not force it."""
    r = contrib.compute_pf(wages=10000.0, **dict(PF, employer_rate_pct=13.0,
                                                 employer_eps_rate_pct=8.5))
    check("employee unchanged", r["pf_employee"], 1200.0)
    check("employer on its own rate", r["pf_employer"], 1300.0)
    check("employer EPS", r["pf_eps_employer"], 850.0)
    check("employer EPF", r["pf_epf_employer"], 450.0)


# ─── Provident fund: the EPS annual ceiling ───────────────────────────────────


def test_eps_annual_ceiling_trims_eps_to_the_headroom():
    """₹14,900 of the ₹15,000 annual ceiling already used leaves ₹100."""
    r = contrib.compute_pf(wages=10000.0, eps_annual_ceiling=15000.0,
                           eps_ytd_before=14900.0, **PF)
    check("EPS limited to the headroom", r["pf_eps_employee"], 100.0)
    check("EPS+EPF still equals the total", r["pf_employee"], 1200.0)
    check("EPF absorbs the trimmed EPS", r["pf_epf_employee"], 1100.0)
    check("ceiling flagged", r["eps_annual_ceiling_applied"], True)


def test_eps_stops_entirely_once_the_annual_ceiling_is_reached():
    """The defect: EPS used to continue for the rest of the year."""
    r = contrib.compute_pf(wages=10000.0, eps_annual_ceiling=15000.0,
                           eps_ytd_before=15000.0, **PF)
    check("EPS stops", r["pf_eps_employee"], 0.0)
    check("employer EPS stops too", r["pf_eps_employer"], 0.0)
    check("the whole contribution falls to EPF", r["pf_epf_employee"], 1200.0)
    check("employee total unchanged", r["pf_employee"], 1200.0)


def test_eps_annual_ceiling_is_not_reapplied_within_the_headroom():
    r = contrib.compute_pf(wages=10000.0, eps_annual_ceiling=15000.0,
                           eps_ytd_before=0.0, **PF)
    check("EPS at full value in month one", r["pf_eps_employee"], 833.0)
    check("ceiling not flagged", r["eps_annual_ceiling_applied"], False)


def test_eps_annual_ceiling_refuses_a_missing_year_to_date():
    """The defect's door: an annual ceiling with a silent zero YTD."""
    raises(lambda: contrib.compute_pf(wages=10000.0, eps_annual_ceiling=15000.0,
                                      **PF),
           "year-to-date")


def test_eps_ytd_without_a_ceiling_is_refused():
    """A year-to-date figure is meaningless without the ceiling it measures."""
    raises(lambda: contrib.compute_pf(wages=10000.0, eps_ytd_before=5000.0, **PF),
           "meaningless without the ceiling")


def test_eps_ytd_of_zero_is_accepted_when_a_ceiling_exists():
    r = contrib.compute_pf(wages=10000.0, eps_annual_ceiling=15000.0,
                           eps_ytd_before=0.0, **PF)
    check("EPS paid", r["pf_eps_employee"], 833.0)


def test_eps_monthly_cap_binds_independently():
    r = contrib.compute_pf(wages=15000.0, eps_monthly_cap=1000.0, **PF)
    check("EPS capped monthly", r["pf_eps_employee"], 1000.0)
    check("monthly cap flagged", r["eps_monthly_cap_applied"], True)


def test_monthly_and_annual_eps_caps_both_apply():
    """The monthly cap bites first; the annual ceiling then trims the remainder."""
    r = contrib.compute_pf(wages=15000.0, eps_monthly_cap=1000.0,
                           eps_annual_ceiling=2500.0, eps_ytd_before=2400.0, **PF)
    check("annual headroom of 100 wins", r["pf_eps_employee"], 100.0)


# ─── Provident fund: voluntary contribution ───────────────────────────────────


def test_voluntary_pf_sits_outside_the_eps_split():
    voluntary = {"rate_pct": 5.0, "counted_in_employee": True,
                 "counted_in_employer": False}
    r = contrib.compute_pf(wages=10000.0, voluntary=voluntary, **PF)
    check("added to the employee total", r["pf_employee"], 1700.0)
    check("EPS unchanged", r["pf_eps_employee"], 833.0)
    check("EPF is not inflated by it", r["pf_epf_employee"], 367.0)
    check("voluntary recorded separately", r["pf_voluntary"], 500.0)


def test_employer_does_not_pay_a_voluntary_contribution_by_default():
    """The defect: the employer's total included the employee's voluntary sum."""
    voluntary = {"rate_pct": 5.0, "counted_in_employee": True,
                 "counted_in_employer": False}
    r = contrib.compute_pf(wages=10000.0, voluntary=voluntary, **PF)
    check("employer total unchanged", r["pf_employer"], 1200.0)
    check("employer side of voluntary", r["pf_voluntary_employer"], 0.0)


def test_employer_matching_voluntary_is_possible_but_must_be_asked_for():
    voluntary = {"rate_pct": 5.0, "counted_in_employee": True,
                 "counted_in_employer": True}
    r = contrib.compute_pf(wages=10000.0, voluntary=voluntary, **PF)
    check("employer pays it too", r["pf_employer"], 1700.0)


def test_voluntary_refuses_ungiven_allocation_flags():
    raises(lambda: contrib.compute_pf(wages=10000.0,
                                      voluntary={"rate_pct": 5.0}, **PF),
           "counted_in_employee")


def test_voluntary_pf_respects_its_cap():
    voluntary = {"rate_pct": 10.0, "cap": 300.0, "counted_in_employee": True,
                 "counted_in_employer": False}
    r = contrib.compute_pf(wages=15000.0, voluntary=voluntary, **PF)
    check("voluntary capped", r["pf_voluntary"], 300.0)


def test_no_voluntary_configuration_means_no_voluntary_contribution():
    r = contrib.compute_pf(wages=10000.0, **PF)
    check("zero", r["pf_voluntary"], 0.0)


# ─── ESI ──────────────────────────────────────────────────────────────────────

# Structurally plausible, amounts invented. The real schedule is CA request 4.1.
ESI = {
    "mode": "band_amount",
    "coverage_ceiling": 25000.0,
    "bands": [
        {"up_to": 3500.0, "employee": 0.0, "employer": 0.0},
        {"up_to": 7500.0, "employee": 21.0, "employer": 175.0},
        {"up_to": 15000.0, "employee": 46.0, "employer": 390.0},
        {"up_to": 25000.0, "employee": 46.0, "employer": 390.0},
    ],
}


def test_esi_band_amount_not_a_percentage():
    """₹21 for the band, not 0.75% of ₹6,000 which would be ₹45."""
    r = contrib.compute_esi(wages=6000.0, schedule=ESI)
    check("employee", r["esi_employee"], 21.0)
    check("employer", r["esi_employer"], 175.0)
    check("mode recorded", r["esi_mode"], "band_amount")


def test_esi_band_boundaries():
    """At and either side of each band edge."""
    for wage, want in ((0.0, 0.0), (3500.0, 0.0), (3500.01, 21.0),
                       (7500.0, 21.0), (7500.01, 46.0), (15000.0, 46.0),
                       (15000.01, 46.0), (25000.0, 46.0)):
        r = contrib.compute_esi(wages=wage, schedule=ESI)
        check(f"employee ESI at {wage:,.2f}", r["esi_employee"], want)


def test_esi_below_the_threshold_contributes_nothing():
    r = contrib.compute_esi(wages=2000.0, schedule=ESI)
    check("nothing", r["esi_employee"], 0.0)
    check("not applicable", r["esi_applicable"], False)


def test_esi_above_the_coverage_ceiling_is_not_applicable():
    r = contrib.compute_esi(wages=30000.0, schedule=ESI)
    check("no contribution", r["esi_employee"], 0.0)
    check("not applicable", r["esi_applicable"], False)
    check("and it says why", r["above_coverage_ceiling"], True)


def test_esi_rate_mode_must_be_declared_provisional():
    """The old behaviour applied a flat percentage unconditionally."""
    rates = {
        "mode": "rate",
        "coverage_ceiling": 25000.0,
        "bands": [{"up_to": 25000.0, "employee_rate_pct": 0.75,
                   "employer_rate_pct": 3.25}],
    }
    message = raises(lambda: contrib.compute_esi(wages=6000.0, schedule=rates),
                     "do not believe is correct")
    check("and it points at the CA request", "4.1" in message, True)
    rates["provisional"] = True
    r = contrib.compute_esi(wages=6000.0, schedule=rates)
    check("then it is allowed and labelled", r["esi_mode"], "rate-provisional")
    check("0.75% of 6,000", r["esi_employee"], 45.0)


def test_esi_with_no_schedule_is_refused():
    raises(lambda: contrib.compute_esi(wages=6000.0, schedule=None),
           "refusing to guess")


def test_esi_undeclared_mode_is_refused():
    raises(lambda: contrib.compute_esi(
        wages=6000.0,
        schedule={"coverage_ceiling": 25000.0, "bands": ESI["bands"]}),
        "declares no usable mode")


def test_esi_bare_band_list_is_refused():
    """A list cannot say which reading it is, which is the whole defect."""
    raises(lambda: contrib.compute_esi(wages=6000.0, schedule=ESI["bands"]),
           "bare list")


def test_esi_missing_coverage_ceiling_is_refused():
    raises(lambda: contrib.compute_esi(
        wages=6000.0, schedule={"mode": "band_amount", "bands": ESI["bands"]}),
        "coverage_ceiling")


def test_esi_gap_between_bands_is_refused():
    gapped = dict(ESI, bands=[ESI["bands"][0], ESI["bands"][2]])
    raises(lambda: contrib.compute_esi(wages=6000.0, schedule=gapped),
           "silently escape ESI")


def test_esi_bands_overlapping_ceiling_are_refused():
    over = dict(ESI, bands=ESI["bands"] + [{"up_to": 30000.0, "employee": 0.0,
                                            "employer": 0.0}])
    raises(lambda: contrib.compute_esi(wages=6000.0, schedule=over),
           "coverage_ceiling")


def test_esi_open_ended_band_is_refused():
    open_ended = dict(ESI, bands=ESI["bands"][:2] +
                      [{"up_to": None, "employee": 0.0, "employer": 0.0}])
    raises(lambda: contrib.compute_esi(wages=6000.0, schedule=open_ended),
           "no upper limit")


# ─── Professional Tax ─────────────────────────────────────────────────────────

PT = [
    {"from": 0, "to": 5000, "employee": 0, "employer": 0},
    {"from": 5000, "to": 10000, "employee": 175, "employer": 175},
    {"from": 10000, "to": None, "employee": 200, "employer": 200},
]


def test_pt_band_selection():
    check("below the first band", contrib.compute_pt(4000.0, PT)["pt_employee"], 0.0)
    check("first paying band", contrib.compute_pt(7000.0, PT)["pt_employee"], 175.0)
    check("top band", contrib.compute_pt(20000.0, PT)["pt_employee"], 200.0)


def test_pt_band_edge_is_a_parameter_not_a_coincidence():
    """₹5,000 falls in two readings; the statute settles which, so it is config."""
    inclusive = contrib.compute_pt(5000.0, PT, boundary="inclusive")
    exclusive = contrib.compute_pt(5000.0, PT, boundary="exclusive")
    check("inclusive keeps the lower band", inclusive["pt_employee"], 0.0)
    check("exclusive moves it up", exclusive["pt_employee"], 175.0)


def test_pt_unknown_boundary_is_refused():
    raises(lambda: contrib.compute_pt(7000.0, PT, boundary="whatever"), "CA request")


def test_pt_annual_cap_stops_the_year():
    r = contrib.compute_pt(7000.0, PT, ytd_pt=2400.0, annual_cap=2500.0)
    check("only the remainder of the cap", r["pt_employee"], 100.0)
    check("and it is noted", r["annual_cap_note"],
          "annual cap reached this month; part-month amount")


def test_pt_annual_cap_already_reached_deducts_nothing():
    r = contrib.compute_pt(7000.0, PT, ytd_pt=2500.0, annual_cap=2500.0)
    check("nothing more", r["pt_employee"], 0.0)
    check("noted", r["annual_cap_note"], "annual cap already reached")


def test_pt_cap_of_zero_is_not_the_same_as_no_cap():
    """The defect: ``if annual_cap:`` treated a configured zero as unconfigured."""
    capped = contrib.compute_pt(7000.0, PT, ytd_pt=0.0, annual_cap=0.0)
    check("nothing deductible", capped["pt_employee"], 0.0)
    check("noted", capped["annual_cap_note"], "annual cap already reached")
    uncapped = contrib.compute_pt(7000.0, PT, annual_cap=None)
    check("no cap means the full slab", uncapped["pt_employee"], 175.0)


def test_pt_does_not_refuse_zero_income():
    """A zero-salary employee owes nothing; that is a valid payroll, not an error."""
    check("nothing due", contrib.compute_pt(0.0, PT)["pt_employee"], 0.0)


def test_pt_refuses_a_table_with_a_gap():
    gapped = [{"from": 0, "to": 5000, "employee": 0},
              {"from": 9000, "to": None, "employee": 200}]
    raises(lambda: contrib.compute_pt(7000.0, gapped), "gap or overlap")


def test_pt_refuses_a_closed_top_band():
    raises(lambda: contrib.compute_pt(60000.0,
                                      [{"from": 0, "to": 50000, "employee": 100}]),
           "must be open-ended")


def test_pt_refuses_a_table_not_starting_at_zero():
    raises(lambda: contrib.compute_pt(1000.0,
                                      [{"from": 5000, "to": None, "employee": 100}]),
           "silently escape PT")


def test_pt_refuses_an_empty_table():
    """The old behaviour returned zero for a State with no PT, silently."""
    raises(lambda: contrib.compute_pt(7000.0, []), "explicit zero band")


def test_pt_zero_band_table_is_how_a_no_pt_state_is_configured():
    """A State that levies no PT must say so, and then it really is zero."""
    no_pt = [{"from": 0, "to": None, "employee": 0, "employer": 0}]
    r = contrib.compute_pt(7000.0, no_pt)
    check("nothing due", r["pt_employee"], 0.0)
    check("employer too", r["pt_employer"], 0.0)


# ─── Gratuity: service months ─────────────────────────────────────────────────


def test_service_months_counts_whole_months():
    check("1 Jan to 15 Feb", grat.service_months(datetime.date(2024, 1, 1),
                                                  datetime.date(2024, 2, 15)), 1)
    check("1 Jan to 28 Feb", grat.service_months(datetime.date(2024, 1, 1),
                                                  datetime.date(2024, 2, 28)), 1)
    check("1 Jan to 1 Mar", grat.service_months(datetime.date(2024, 1, 1),
                                                 datetime.date(2024, 3, 1)), 2)


def test_service_months_exclusive_of_the_ending_day():
    check("1 Jan to 31 Dec is 11 whole months",
          grat.service_months(datetime.date(2024, 1, 1),
                              datetime.date(2024, 12, 31)), 11)


def test_service_months_inclusive_end_counts_a_fixed_term_in_full():
    """1 Jan to 31 Dec is twelve months for a fixed term, so a 1-year term counts."""
    months = grat.service_months(datetime.date(2024, 1, 1),
                                 datetime.date(2024, 12, 31), inclusive_end=True)
    check("inclusive end", months, 12)


def test_service_months_handles_a_leap_february():
    months = grat.service_months(datetime.date(2024, 1, 31),
                                 datetime.date(2024, 2, 29), inclusive_end=True)
    check("Jan 31 to Feb 29 inclusive is two months", months, 2)


def test_service_months_before_joining_is_zero():
    check("no service", grat.service_months(datetime.date(2024, 6, 1),
                                            datetime.date(2024, 1, 1)), 0)


def test_service_months_refuses_missing_dates():
    raises(lambda: grat.service_months(None, datetime.date(2024, 1, 1)))


# ─── Gratuity: the six-month boundary ─────────────────────────────────────────


def test_remainder_of_exactly_six_months_does_not_count_by_default():
    """The defect: exactly six months was counted as a full year.

    5 years and 6 months is 66 months: 5 whole years, remainder 6. The statute
    says 'part thereof in excess of six months', so six is not in excess.
    """
    years, note = grat.countable_years(66)
    check("66 months is 5 years", years, 5.0)
    check("and the note explains it", "exclusive" in note, True)


def test_remainder_of_seven_months_counts():
    check("67 months rounds up", grat.countable_years(67)[0], 6.0)


def test_remainder_of_five_months_does_not_count():
    check("65 months stays at 5", grat.countable_years(65)[0], 5.0)


def test_the_boundary_is_a_parameter_for_the_other_reading():
    years, note = grat.countable_years(66, boundary="inclusive")
    check("inclusive reading counts it", years, 6.0)
    check("and says so", "inclusive" in note, True)


def test_unknown_boundary_is_refused():
    raises(lambda: grat.countable_years(66, boundary="round"), "CA request")


def test_pro_rata_counts_every_month():
    check("18 months is 1.5 years",
          grat.countable_years(18, pro_rata=True)[0], 1.5)


def test_no_service_is_zero_years_not_an_error():
    check("zero", grat.countable_years(0)[0], 0.0)


def test_negative_service_is_refused():
    raises(lambda: grat.countable_years(-1))


# ─── Gratuity: the wage basis ─────────────────────────────────────────────────


def test_wage_basis_requires_a_gross_figure():
    """The defect: it used to fall back to CTC/12, overstating the basis."""
    message = raises(lambda: grat.wage_basis_from_payslip_gross(None),
                     "refusing to substitute CTC")
    check("and it points at the CA request", "section 2" in message, True)


def test_wage_basis_refuses_zero():
    """A zero basis produces a zero gratuity that looks valid."""
    raises(lambda: grat.wage_basis_from_payslip_gross(0.0), "must be positive")


def test_wage_basis_accepts_a_real_figure():
    check("as given", grat.wage_basis_from_payslip_gross(60000.0), 60000.0)


# ─── Gratuity: the amount ─────────────────────────────────────────────────────


def test_gratuity_refuses_a_missing_divisor():
    raises(lambda: grat.compute_gratuity(wage_basis=60000.0, days_per_year=15.0,
                                         countable_years_value=5.0,
                                         wages_divisor=None),
           "not configured")


def test_gratuity_refuses_a_missing_days_per_year():
    raises(lambda: grat.compute_gratuity(wage_basis=60000.0, days_per_year=None,
                                         countable_years_value=5.0,
                                         wages_divisor=26.0),
           "not configured")


def test_gratuity_amount_with_a_synthetic_divisor():
    r = grat.compute_gratuity(wage_basis=60000.0, days_per_year=15.0,
                              countable_years_value=5.0, wages_divisor=26.0)
    # 60000 / 26 x 15 x 5
    check("daily wage", r["daily_wage"], 2307.69)
    check("five years", r["uncapped_amount"], 173076.92)
    check("payable is the full amount", r["payable"], 173076.92)


def test_gratuity_ceiling_reports_excess_separately():
    r = grat.compute_gratuity(wage_basis=60000.0, days_per_year=15.0,
                              countable_years_value=5.0, wages_divisor=26.0,
                              ceiling=100000.0)
    check("payable is the ceiling", r["payable"], 100000.0)
    check("the excess is not payable", r["excess_over_ceiling"], 73076.92)
    check("flagged", r["ceiling_applied"], True)


def test_gratuity_below_the_ceiling_is_uncapped():
    r = grat.compute_gratuity(wage_basis=60000.0, days_per_year=15.0,
                              countable_years_value=1.0, wages_divisor=26.0,
                              ceiling=100000.0)
    check("full amount", r["payable"], 34615.38)
    check("no excess", r["excess_over_ceiling"], 0.0)


def test_gratuity_without_a_ceiling_is_not_a_ceiling_of_zero():
    r = grat.compute_gratuity(wage_basis=60000.0, days_per_year=15.0,
                              countable_years_value=1.0, wages_divisor=26.0)
    check("full amount payable", r["payable"], 34615.38)
    check("not flagged as capped", r["ceiling_applied"], False)


def test_gratuity_of_no_service_is_zero():
    r = grat.compute_gratuity(wage_basis=60000.0, days_per_year=15.0,
                              countable_years_value=0.0, wages_divisor=26.0)
    check("nothing payable", r["payable"], 0.0)


def test_gratuity_interest_refuses_a_missing_rate():
    """The register claims interest is owed; the rate is unknown."""
    raises(lambda: grat.gratuity_interest(100000.0, days_late=10, rate_pct=None),
           "not configured")


def test_gratuity_interest_refuses_a_zero_rate():
    raises(lambda: grat.gratuity_interest(100000.0, 10, 0.0), "must be positive")


def test_gratuity_interest_computed():
    simple = grat.gratuity_interest(100000.0, days_late=1095, rate_pct=12.0)
    check("simple, three years", simple, 36000.0)
    compounded = grat.gratuity_interest(100000.0, days_late=1095, rate_pct=12.0,
                                        compounding="compounded_annual")
    check("compounded exceeds simple", compounded > simple, True)


def test_gratuity_interest_refuses_an_unknown_basis():
    raises(lambda: grat.gratuity_interest(100000.0, 10, 12.0, compounding="daily"),
           "CA request")


# ─── Structural guards ────────────────────────────────────────────────────────


def test_modules_have_no_odoo_import():
    for path in (_CONTRIB_PATH, _GRAT_PATH):
        source = open(path).read()
        for forbidden in ("import odoo", "from odoo", "odoo.exceptions"):
            if forbidden in source:
                raise Failure(f"{os.path.basename(path)} contains '{forbidden}'")


def test_no_mirrored_copies():
    """The production code must import these modules, not reimplement them."""
    india = open(os.path.join(_REPO, "addons", "hrms_statutory", "models",
                              "india.py")).read()
    gratuity = open(os.path.join(_REPO, "addons", "hrms_statutory", "models",
                                 "gratuity.py")).read()
    if "contribution_arithmetic" not in india:
        raise Failure(
            "india.py no longer uses contribution_arithmetic; these tests are "
            "now testing a module payroll does not use"
        )
    if "gratuity_arithmetic" not in gratuity:
        raise Failure(
            "gratuity.py no longer uses gratuity_arithmetic; these tests are "
            "now testing a module payroll does not use"
        )


def _code_only(rel):
    """Source with comments and string literals removed.

    The guards below look for arithmetic that used to be inline. Those expressions
    also appear in the docstrings that document the defects, so the prose has to
    come out before the search, or every fix trips its own regression test.
    """
    import io
    import tokenize

    path = os.path.join(_REPO, *rel)
    source = open(path).read()
    kept = []
    with open(path, "rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def test_inline_pf_and_esi_arithmetic_is_gone():
    """The old inline bodies must not survive alongside the extraction."""
    code = _code_only(("addons", "hrms_statutory", "models", "india.py"))
    for pattern, why in (
        ("base * ( emp_rate / 100.0 )", "employer rate assumed equal to the employee's"),
        ("gross * emp_rate", "ESI as a flat percentage of wages"),
        ("annual_cap and ( ytd_pt + pt_employee )", "PT cap falsiness"),
        ('"pt_employee" : 0.0',
         "PT returning a silent zero for an unconfigured State"),
        ("abs( l [ \"amount\" ] )", "deduction amounts masked by abs()"),
    ):
        if pattern in code:
            raise Failure(
                f"india.py still contains {pattern!r} ({why}). These tests are "
                f"now testing a module payroll does not use."
            )


def test_ctc_wage_basis_does_not_survive():
    """The CTC/12 gratuity basis must not reappear in any caller."""
    for rel in (("addons", "hrms_statutory", "models", "gratuity.py"),
                ("addons", "hrms_fnf", "models", "encashment.py"),
                ("addons", "hrms_fnf", "models", "settlement.py")):
        code = _code_only(rel)
        if "hrms_ctc" not in code:
            continue
        raise Failure(
            f"{rel[-1]}: hrms_ctc is referenced in live code. CTC includes employer "
            f"contributions and is not statutory 'wages'; it must not be used as a "
            f"wage basis for gratuity or leave encashment. See "
            f"gratuity_arithmetic.wage_basis_from_payslip_gross."
        )


def test_leave_accrual_square_is_gone():
    """``months * months`` entitled 18 months of service to 324 days of leave."""
    code = _code_only(("addons", "hrms_fnf", "models", "encashment.py"))
    for pattern in ("months * months", "accrued_leave_days("):
        if pattern in code and "settlement_arithmetic" not in code:
            raise Failure(
                f"encashment.py still squares the service months ({pattern!r}) "
                "instead of calling settlement_arithmetic.accrued_leave_days"
            )


def test_dynamic_invented_config_codes_are_gone():
    """A config code built at runtime was never in the catalog, so it never existed.

    ``IN.LEAVE.ACCRUAL_DAYS.<leave type>`` was resolved per leave type and the
    resulting UserError was swallowed into zero. The accrual now comes from the
    single catalog code ``IN.LEAVE.ACCRUAL_DAYS_PER_YEAR``.
    """
    catalog = open(os.path.join(_REPO, "addons", "hrms_statutory", "models",
                                "catalog.py")).read()
    for rel in (("addons", "hrms_fnf", "models", "encashment.py"),
                ("addons", "hrms_statutory", "models", "india.py"),
                ("addons", "hrms_statutory", "models", "gratuity.py")):
        code = _code_only(rel)
        for prefix in ("IN.LEAVE.ACCRUAL_DAYS.", "IN.PF.WAGE_CEILING.", "IN.PT."):
            if f'"{prefix}' in code or f"'{prefix}" in code:
                raise Failure(
                    f"{rel[-1]} builds the config code {prefix!r} at runtime; every "
                    "code must exist in the catalog, or the lookup fails and gets "
                    "swallowed into zero"
                )
    if "IN.LEAVE.ACCRUAL_DAYS_PER_YEAR" not in catalog:
        raise Failure(
            "the catalog no longer carries IN.LEAVE.ACCRUAL_DAYS_PER_YEAR, so "
            "leave accrual has no configured source at all"
        )


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
