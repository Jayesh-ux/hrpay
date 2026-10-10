# HRMS Design System

Design tokens and component contracts for the HRMS product. This document is
the single source of truth for colour, type, spacing and component styling. It
is tool-agnostic: it applies to an interim Odoo-stock restyle and to the
separate front end that is the target.

Status: **proposed — awaiting sign-off.** No UI is built against these tokens
yet.

---

## 1. Context and decisions

- The visual reference is a **custom-built web app**, not stock Odoo. Odoo's
  lists, forms, settings and chatter are drawn by Odoo's own components, so a
  restyle can get close on colour but will not match a custom app everywhere.
- Chosen direction:
  - **Target (route B):** a separate front end on top of Odoo, served from the
    REST API (`hrms_api`, not yet built). It matches the reference exactly and
    is the real product surface for employees and HR.
  - **Interim (route A, light version):** Odoo stays the engine and the admin
    console. Statutory, legal-basis and sign-off screens are built in Odoo's
    **stock layout** (no global sidebar/layout overrides — those broke an
    earlier attempt).
- **Dark is the default**, with a **light/dark toggle**. Both themes use the
  same token names; only the values change.
- **Do not copy the reference product.** Take structure and feel only. Use our
  own name, icons, copy and demo data.

## 2. Principles

1. **Legibility first.** Body text meets WCAG AA (>= 4.5:1). Decoration never
   costs readability. Nothing renders below 12px.
2. **Calm surfaces.** Few glows and gradients. No decorative glow at all
   (performance and readability on ordinary office PCs).
3. **One font, bundled locally.** No CDN. One family, a few weights.
4. **Consistent rhythm.** An 8px spacing grid; a small, fixed radius scale.
5. **Tokens, not literals.** Components reference tokens, never raw hex.

## 3. Colour tokens

`accent` is a **fill/edge** colour (use with white or dark text as specified);
`accent-text` is the variant used when the accent is applied to **text on the
theme background**, so it still meets AA.

| Token           | Dark (default) | Light (derived) | Typical use |
|-----------------|----------------|-----------------|-------------|
| `bg`            | `#0b1020`      | `#f5f6fb`       | App background |
| `sidebar`       | `#0f1629`      | `#ffffff`       | Fixed left sidebar |
| `surface`       | `#131c33`      | `#ffffff`       | Cards, tables, panels |
| `surface-raised`| `#172140`      | `#f7f8fc`       | Hover, raised rows, inputs |
| `border`        | `#25304d`      | `#d7dbe8`       | Dividers, card/table borders |
| `text`          | `#e8ecf8`      | `#14192b`       | Primary text |
| `text-muted`    | `#9aa6c4`      | `#5a6478`       | Secondary text |
| `text-subtle`   | `#8591b3`      | `#6b7385`       | Tertiary / captions |
| `accent`        | `#6d4aff`      | `#5b34e8`       | Primary buttons, active nav, KPI top bar (fill) |
| `accent-text`   | `#a995ff`      | `#4a22d6`       | Accent-coloured text on `bg`/`surface` |
| `success`       | `#4ade9a`      | `#1c8a53`       | Status pill: approved/paid |
| `warning`       | `#fbbf5a`      | `#b26a00`       | Status pill: pending/attention |
| `danger`        | `#ff7a8a`      | `#c8324a`       | Status pill: failed/refused |
| `info`          | `#4cc3ff`      | `#0b6fa4`       | Status pill: info/processing |

Notes:
- Dark values are the source of truth from the brief. **Light values are
  derived** to preserve the same semantics and AA contrast and are proposed for
  confirmation.
- Status colours are used as text-on-tinted-chip; the chip background is the
  status colour at low alpha over `surface`, and the text uses the theme's
  status colour. Verify >= 4.5:1 for the chip text in both themes.
- The reference's brand orange is **not** adopted; accent is violet `#6d4aff`.

## 4. Typography

- **One family, bundled locally** (no CDN, no Google Fonts link). Candidate:
  *Plus Jakarta Sans* (SIL OFL) shipped as a self-hosted variable font.
  Fallback stack: `system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`.
- **Scale** (px): `12 / 13 / 14 / 16 / 22 / 30`.
  - `30` — page title (display)
  - `22` — section title / KPI value
  - `16` — emphasised body
  - `14` — body (default)
  - `13` — compact body / table cells
  - `12` — labels/captions (minimum; never smaller)
- **Weights:** 400 (regular), 500 (medium), 600 (semibold), 700 (bold).
- **Content rules:** sentence case for labels and headers (avoid all-caps
  micro-labels — poor legibility). Line height 1.5 for body text.

## 5. Spacing and radii

- **Spacing:** 8px grid — `4, 8, 16, 24, 32, 48` (4 is the only half-step, for
  tight icon/label gaps).
- **Radii:** `8` (inputs, chips, small controls), `12` (cards, tables), `14`
  (large cards, modals). Pills use `9999px`.
- **Borders:** 1px `border`; focus ring uses `accent`.

## 6. Components

- **Sidebar (fixed, left).** Grouped sections with a small section heading
  (sentence case, `text-subtle`, size 12) above each group. Active item: `accent`
  fill or `accent-text` text with an `accent` left indicator. Collapsible.
- **Page header card.** One per page. Title (`30`, `text`), optional subtitle
  (`14`, `text-muted`), and a right-aligned primary action. Sits on `surface`
  with a `12` radius and 1px `border`.
- **KPI card.** A `surface` card with a **2px top accent bar** (`accent`) and an
  **icon tile** (rounded `8`, tinted background, status/accent icon). Big value
  (`22`, `text`), label (`13`, `text-muted`), optional delta (success/danger).
- **Filter bar.** A row of compact controls (search input, selects, date range)
  on `surface-raised`, 8px radius, 8px gaps, aligned to the 8px grid.
- **Table.** Header row `13`/semibold/`text-muted`; body rows `13`, `text`,
  1px `border` row separators, hover row `surface-raised`. Right-align numerics.
- **Status pill.** Rounded pill, tinted background, sentence-case label sized
  12, coloured per status token (`success`/`warning`/`danger`/`info`).
- **Segmented tabs.** A single bordered track; the active segment is an `accent`
  fill with white text; inactive labels use `text-muted`. Keyboard focusable.

## 7. Accessibility and content rules

- Body text contrast **>= 4.5:1** in both themes.
- **No text below 12px.**
- **No decorative glow** (box-shadow glows, neon halos).
- Gradients are allowed only where they do not reduce text contrast.
- Sentence case for labels and headers.
- Focus states must be visible (accent focus ring) and keyboard reachable.
- Colour is never the only signal (status pills pair colour with text).

## 7a. Non-goals

- No CDN fonts or external asset hosts.
- No global Odoo layout overrides (the earlier sidebar override is retired).
- No dependency on the reference product's name, icons, copy or data.

## 8. Change log

- 2026-10-10 — Initial tokens and component contracts recorded (this file).
