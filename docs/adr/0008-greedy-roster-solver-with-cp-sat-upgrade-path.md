# ADR-0008 — Ship the roster solver as a greedy, explainable heuristic; CP-SAT is a documented upgrade

- **Status:** ✅ **Accepted** (2026-10-05)
- **Date:** 2026-10-05

## Context

Phase 1 needs to fill a staffing demand curve: for each establishment, weekday and
shift, a required headcount, some slots of which require particular skills. The
constraints that actually bind are:

- contractual weekly hour ceiling (e.g. 48h)
- contractual maximum days per ISO week (e.g. 6)
- minimum rest between shifts
- maximum consecutive rostered days (fatigue)
- skill requirements
- declared unavailability and approved leave
- night-shift burden

Rostering is formally NP-hard. The question is not whether to use an exact solver
but whether an *inexact* one is acceptable here, given that this decides who works
which night.

There was no runtime available while this was written: the constraint arithmetic
was verified standalone, not inside Odoo.

## Decision

Ship a **deterministic greedy heuristic**, in this priority order:

1. Mandatory cover. Where demand exceeds the eligible pool, report the shortfall
   with per-slot blocker counts.
2. Skills before availability.
3. Availability before preference.
4. Rest, weekly hour ceiling, weekly day cap and consecutive-day cap are hard
   constraints, evaluated before an assignment is proposed.

Within the eligible set, rank by (night-shift credits, skill specificity,
preference, current load, employee id). The employee id is a deterministic
tie-break so the same inputs always give the same roster — an auditable roster
must be reproducible.

The solver never writes assignments. It persists a proposal plus its unfilled
list, and applying a proposal creates **draft** assignments only. A proposal with
any unfilled demand cannot be applied at all.

## Rationale

**A shortfall a manager can explain beats a schedule that is optimal and cannot
be.** Double-booking an employee to close a gap produces a roster that looks
complete and pays overtime for nobody who was there. The heuristic deliberately
fails visibly.

**Every assignment must be defensible after the fact.** Payroll, labour
inspectors and employees all ask the same question: why was this person on this
shift? `proposal_json` carries the reason string for each assignment
("exact skill match", "employee requested this shift", "lightest current load")
and `unfilled_json` carries why each gap could not be filled. An optimal solver
would need a separate proof or post-hoc explanation layer to answer the same
question, which is most of the work anyway.

**Reproducibility is a compliance property here.** The deterministic tie-break
means a published roster can be re-derived from the same inputs. That matters
because statutory calculations snapshot the roster, and a discrepancy has to be
resolvable.

**Greedy is fast enough to be run on every roster change.** The whole demand
curve is processed in memory in a single pass; no search tree.

## Consequences

### Accepted

- **Suboptimal rosters.** The greedy pass never backtracks, so it can decline an
  assignment that a different arrangement would have allowed. This is documented
  in the module docstring rather than hidden.
- **Preference is soft.** An employee's requested shift is honoured only when
  cover and every hard constraint are already satisfied.
- **Load balancing is approximate.** Balancing is by current assignment count,
  not by remaining capacity.

### Known limitations, stated rather than discovered later

- The solver does **not** enforce statutory overtime caps or day limits from
  signed-off statutory codes. `SolverSetting` limits are establishment inputs
  entered by a manager. If a statutory limit is stricter than the configured
  limit, the statutory engine at payroll time is what catches it, not the solver.
  Wiring `hrms.statutory.context` into the solver is a known gap, not a
  deliberate omission.
- Night-shift burden is bounded only when `night_shift_rotation` is enabled.
- Fairness across employees (e.g. equal distribution of undesirable shifts over a
  quarter) is out of scope. The per-employee stats are reported so a manager can
  see it, but nothing enforces it.

## Upgrade path

CP-SAT (OR-Tools) is the planned replacement when any of these become true:

1. An establishment's shortfall rate becomes material, or managers start editing
   solver output heavily enough that the editing cost exceeds the cover gap.
2. Multi-establishment rostering with inter-establishment transfers.
3. Fairness constraints are required by contract.
4. Shift patterns gain dependencies beyond the current per-slot model
   (e.g. "this shift requires the previous night's shift to be filled").

When that happens:

- Keep the model in `SolverSetting`; CP-SAT reads the same limits, so no
  configuration migration is needed.
- Keep `proposal_json` / `unfilled_json` / `SolverResult`; the CP-SAT path emits
  the same shape, so views and the apply path are unchanged.
- Keep `constraint_signatures` coverage: the existing standalone scenarios
  describe the constraint semantics that must still hold, and become the
  regression suite proving the CP-SAT model was implemented correctly rather
  than plausibly.
- Replace the greedy ranking with a documented objective function and
  tie-break policy. Report the objective (total unfilled slots, then total
  preference violations, then fairness deviation) rather than a single score.

## Related

- ADR-0006 (immutable versioned calculations) — the roster snapshot that payroll
  consumes is checksummed against the published period.
- ADR-0003 (statutory rules are bespoke) — the reason statutory caps are not
  hardcoded into the solver.