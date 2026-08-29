# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** PATRICK
**Generated (pass 1, generator):** 2026-08-22 19:13:45
**Locked (manual, pass 3):** 2026-08-22
**Category:** Financial Dashboard (dashboard style, manually locked — no `landing.csv` pattern exists for this category, see Page Pattern below)

---

## Global Rules

### Color Palette

Locked from generator pass 2 ("SaaS dashboard internal admin" query — the only concrete dark/status-color hex set produced across the 3 passages).

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Background | `#0F172A` | `--color-background` |
| Card / Surface | `#1B2336` | `--color-card` |
| Primary (structure) | `#1E293B` | `--color-primary` |
| Secondary | `#334155` | `--color-secondary` |
| Accent (positive / vert) | `#22C55E` | `--color-accent` |
| Destructive (alerte / rouge) | `#EF4444` | `--color-destructive` |
| Warning (à vérifier / ambre) | `#F59E0B` | `--color-warning` |
| Foreground (texte) | `#F8FAFC` | `--color-foreground` |
| Muted | `#272F42` | `--color-muted` |
| Muted Foreground | `#94A3B8` | `--color-muted-foreground` |
| Border | `#64748B` | `--color-border` |
| Ring | `#FFFFFF` | `--color-ring` |
| On Accent | `#0F172A` | `--color-on-accent` |
| On Destructive | `#000000` | `--color-on-destructive` |

**Color Notes:** Dark tech + status green/red. Red confirmed `#EF4444` (was unspecified in the prior chat summary — full hex table always had it). Border corrected from `#475569` (2.36:1 on `#0F172A`, fails WCAG 1.4.11 non-text 3:1) to `#64748B` (3.75:1) — same slate family, next step up (slate-500 vs slate-600).

**Warning token (added post-lock, migration Cockpit v2 session 3):** the original 3 generator passes never produced a third status color (only green/red) — real pages (`run_detail.html`/`target.html`/`index.html`) needed a distinct "flag, not broken" state (p-value DM non significative, stabilité Jaccard sous seuil, échec du fetch movers) that a stopgap (`color-mix` depuis `--color-destructive`) covered provisionally. `#F59E0B` chosen (Tailwind `amber-500`) for the same reason `--color-accent`/`--color-destructive` are `green-500`/`red-500` — same weight, same family as the rest of the locked palette, not an arbitrary pick. Contrast measured (WCAG relative-luminance formula, same method as the Border correction above): `#F59E0B` vs `#0F172A` (background) = **8.31:1**, vs `#1B2336` (card) = **7.30:1** — both clear WCAG 1.4.11 non-text (≥3:1) and even AA normal-text (≥4.5:1) with margin, used as plain colored text (`.metric-value.status-warning`) as well as a tinted badge/banner (`.status-badge.status-warning`, `.banner-warning`), same tinted-background convention already used for `status-ok`/`status-error` (no separate `--color-on-warning` needed).

### Typography

**Stable across all 3 generator passes — no reroll, locked as-is.**

- **Heading Font:** Fira Code
- **Body Font:** Fira Sans
- **Mood:** dashboard, data, analytics, code, technical, precise
- **Google Fonts:** [Fira Code + Fira Sans](https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
```

### Spacing Variables

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding (unused — no hero in this pattern) |

### Shadow Depths

> ✅ Recalibrated for the dark `#0F172A` background (was: light-mode black-alpha values, nearly invisible on near-black). A dark drop shadow on an already-dark page adds ~nothing — depth here comes from (1) a low-alpha **white ring** (`0 0 0 1px rgba(255,255,255,α)`) that draws the card edge against the background, combined with (2) the existing lighter card surface (`#1B2336` vs `#0F172A` background — Material dark-theme elevation-by-surface-lightness), plus a larger, softer black blur for ambient depth at bigger elevations (still contributes once blur radius is large enough to spread past the near-black floor). Validated visually — see report.

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 0 0 1px rgba(255,255,255,0.04), 0 1px 3px rgba(0,0,0,0.4)` | Subtle lift, resting state |
| `--shadow-md` | `0 0 0 1px rgba(255,255,255,0.06), 0 6px 16px rgba(0,0,0,0.5)` | Cards, buttons |
| `--shadow-lg` | `0 0 0 1px rgba(255,255,255,0.08), 0 14px 32px rgba(0,0,0,0.55)` | Modals, dropdowns, card hover |
| `--shadow-xl` | `0 0 0 1px rgba(255,255,255,0.10), 0 24px 56px rgba(0,0,0,0.6)` | Featured cards, popovers |

---

## Component Specs

Updated to reference the locked palette tokens (was hardcoded to the abandoned pass-1 blue/amber palette).

```css
/* Primary Button */
.btn-primary {
  background: var(--color-accent);
  color: var(--color-on-accent);
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: var(--color-foreground);
  border: 2px solid var(--color-border);
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Cards

```css
.card {
  background: var(--color-card);
  color: var(--color-foreground);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
```

### Inputs

```css
.input {
  background: var(--color-background);
  color: var(--color-foreground);
  padding: 12px 16px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: var(--color-ring);
  outline: none;
  box-shadow: 0 0 0 3px rgba(255,255,255,0.15);
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
}

.modal {
  background: var(--color-card);
  color: var(--color-foreground);
  border: 1px solid var(--color-border);
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Data-Dense Dashboard *(confirmed stable across all 3 passages — locked)*

**Dashboard Style:** Financial Dashboard *(locked — from `products.csv` product-type match, not the generic Style catalog)*

**Keywords:** Multiple charts/widgets, data tables, KPI cards, minimal padding, grid layout, space-efficient, maximum data visibility

**Best For:** Business intelligence dashboards, financial analytics, enterprise reporting, operational dashboards, data warehousing

**Key Effects:** Hover tooltips, chart zoom on click, row highlighting on hover, smooth filter animations, data loading spinners

### Page Pattern

**Pattern Name:** Internal Cockpit *(hand-authored — no entry in `landing.csv` fits; that catalog is 100% marketing-landing patterns. `products.csv` explicitly marks "Financial Dashboard" / "Analytics Dashboard" as `Landing Page Pattern: N/A`, which is the signal this pattern replaces.)*

- **Layout:** Fixed left sidebar navigation. No hero, no marketing header.
- **Content zones:** Top row = KPI card grid. Below = dense data tables / charts (drill-down, comparative).
- **States:** Explicit empty state and loading state (skeleton/spinner) per data zone — no bare blank sections.
- **No conversion flow:** no CTA, no "start trial", no pricing, no client logos, no funnel steps.

**Explicitly avoid (pattern-level, in addition to Style anti-patterns below):**
- ❌ Full-width hero / marketing header
- ❌ Commercial CTA ("Start trial", "Contact Sales", "Book a demo")
- ❌ Client logos / trust badges
- ❌ Multi-step funnel or path-selection ("I am a...")

---

## Anti-Patterns (Do NOT Use)

*(Style-level, from Data-Dense Dashboard — unchanged, kept)*

- ❌ Ornate design
- ❌ No filtering

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Dark mode: text contrast 4.5:1 minimum (background is dark by default now — verify against `#0F172A`, not the old light background)
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind the fixed sidebar
- [ ] No horizontal scroll on mobile
