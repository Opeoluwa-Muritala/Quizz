# Aptus — Frontend Design Instructions & Strict Guardrails

This document is a build-time contract, not inspiration. Where a number is given, treat it as a hard limit — do not introduce a new value without updating this file first. Where a rule says "only," nothing else is permitted without a documented exception.

This extends the general design judgment in `frontend-design` (distinctiveness, restraint, one bold move per screen, real copy over lorem ipsum) with concrete, enforceable constraints for Aptus specifically — a recruitment/ATS admin product with dense data tables, multi-stage pipelines, and frequent form entry.

---

## 1. Brand Tokens (source of truth)

**Colors — use CSS variables, never hardcode hex in components:**

```css
--color-primary: #241E4E;      /* Deep Indigo — nav, headers, primary buttons */
--color-accent: #0FA3A3;       /* Signal Teal — CTAs, links, active states */
--color-highlight: #F2A93B;    /* Warm Amber — badges, progress, status only */
--color-bg: #F7F7F5;           /* Off-White — page background */
--color-text: #1E1E24;         /* Charcoal — body text */
--color-success: #2E9E6B;
--color-error: #C24545;
```

Hard limit: **no more than 2 accent colors visible in any single viewport** (Teal + one of Amber/Success/Error). Indigo and Off-White/Charcoal don't count toward this limit — they're structural, not accent.

**Typography:**
- Headings: one geometric sans (Sora, Manrope, or Space Grotesk) — pick one at project start, do not mix.
- Body: one humanist sans (Inter or DM Sans).
- Type scale: 12 / 14 / 16 / 20 / 24 / 32 / 40px only. No arbitrary in-between sizes.
- Line length: body text max 80 characters per line; forms and table cells are exempt.
- No all-caps labels. No single-word accent styling in headings (no random bold/italic/colored word inside a heading).

---

## 2. Global Layout

- Base spacing unit: **8px**. All padding/margin values must be multiples of 8 (4px allowed only for icon-to-text gaps inside a single control).
- Page grid: 12-column, 24px gutter, max content width 1280px, centered.
- Breakpoints: 1280px (desktop), 1024px (small desktop/tablet landscape), 768px (tablet), 480px (mobile). Every admin screen must be usable at 1024px minimum; candidate-facing screens must work down to 375px.
- Border-radius: exactly two values in the whole product — **6px** (inputs, buttons, small controls) and **12px** (cards, modals, panels). Nothing else. No fully-rounded (pill) buttons except toggle/status chips.
- Shadows: exactly one elevation value for resting cards (`0 1px 2px rgba(30,30,36,0.08)`) and one for raised/floating elements like modals and dropdowns (`0 8px 24px rgba(30,30,36,0.16)`). Do not invent additional shadow depths.

---

## 3. Top Bar

- Height: fixed **64px**, sticky on scroll, background `--color-primary` with white/off-white text and icons.
- Contents, left to right, no exceptions: product wordmark/logo (left-aligned) → [optional] current section label → flexible spacer → global search (admin only, 320px wide, collapses to icon under 1024px) → notifications icon → admin account menu (right-most).
- Max 5 interactive elements in the top bar besides the logo. If a 6th is needed, it goes in the sidebar or an overflow menu — do not widen the bar's scope.
- No secondary nav links floated in the top bar. Navigation lives in the sidebar only.

---

## 4. Sidebar

- Width: **260px expanded**, **72px collapsed** (icon-only). Collapse is user-toggleable and persists per session.
- Structure top to bottom: primary nav items (pipeline stages, job postings, candidates, reports) → divider → secondary items (settings, help) → nothing below settings.
- Max **8 top-level nav items**. If the product grows past 8 sections, group into collapsible sections — do not shrink row height to fit more.
- Each nav row: 40px height, one icon (20px) + one label. Active state = Teal left-border (3px) + Indigo-tinted background, never color-only (must remain distinguishable without color for accessibility).
- No nested nav deeper than 2 levels (section → sub-item). A 3rd level means the IA needs rethinking, not a deeper tree.

---

## 5. Homepage / Dashboard

- One hero metric or moment at the top — not four equal-weight stat cards competing for attention. Pick the single number or state that matters most right now (e.g., "12 candidates awaiting review") and give it visual priority; supporting stats are smaller and secondary.
- Below the hero: a pipeline funnel view (stage counts) is the primary content — this is the product's most characteristic view, it should not be buried under generic widgets.
- Max 3 dashboard "cards" besides the hero and funnel. Do not build a generic 6-card SaaS grid.
- No decorative gradients. No stock illustration. If an empty state needs an image, use a simple single-color line icon, not an illustration pack.

---

## 6. Textboxes / Form Inputs

- Height: **40px** single-line inputs, **standard textarea min-height 96px**.
- One input style across the entire product: 1px border `#D8D8D4` resting, `--color-accent` border + 2px focus ring on focus, `--color-error` border + inline message on error. No alternate "underline" or "filled" input styles mixed in.
- Label position: always above the input, never inside as placeholder-only (placeholder text may supplement, never replace, a label).
- Error messages: appear directly below the field, in `--color-error`, stating what's wrong and how to fix it — never just "Invalid input."
- Max line length inside a single-line text input is unconstrained (it's a field, not prose), but helper/error text under a field wraps at the field's width.

---

## 7. Buttons & CTAs

- Three variants only: **Primary** (solid Teal, white text), **Secondary** (Indigo outline, Indigo text), **Tertiary/text** (no border, Teal text). No 4th variant without updating this doc.
- Height: 40px standard, 32px for compact/inline table-row actions. No other heights.
- One primary button per view/section. If two actions compete, one is Primary and the other is Secondary — never two Primary buttons side by side.
- Button copy is a verb phrase matching the result: "Send offer," not "Submit." The confirmation toast after clicking must reuse the same verb ("Offer sent").
- Icon-only buttons (no visible label) require a tooltip and an `aria-label`. Never ship an icon-only button without one of these.

---

## 8. Dropdowns / Selects

- Trigger height matches standard input height (40px). Chevron icon, 16px, always right-aligned inside the trigger.
- Open panel: max-height **320px**, scrolls internally beyond that — never pushes page layout. Panel uses the "raised" shadow token from Section 2.
- Options list: max 8 visible without scroll; if the option count regularly exceeds ~15, use a searchable/filterable dropdown instead of a plain scroll list (this applies directly to job/stage/interviewer selects).
- Multi-select uses checkboxes inside the panel + a chip/tag summary in the closed trigger (e.g., "3 selected") — never a comma-jammed list of full values in the closed state.
- No custom-styled native `<select>` hacks that break keyboard navigation. Build with a proper listbox pattern (roving focus, arrow-key navigation, Esc to close).

---

## 9. Icons

- One icon library for the entire product, outline/stroke style only (e.g., Lucide or Feather — pick one at project start and do not mix libraries).
- Two sizes only: **16px** (inline with text, table rows) and **20px** (standalone buttons, nav, top bar). No other icon sizes.
- Stroke width: consistent across every icon instance (library default — do not override per-icon).
- Icons are never purely decorative next to a label that already says the same thing in words unless the icon also functions as a standalone control at narrow widths (e.g., collapses to icon-only in the sidebar).
- Status/stage icons (passed, flagged, rejected, etc.) must pair color with a distinct shape/icon — never rely on color alone.

---

## 10. Data Tables (candidate lists, job lists)

- Row height: 48px standard, 40px in a "compact" density toggle if offered.
- Sticky header row on scroll. Sortable columns show a single small arrow indicator, not a full icon-button per column.
- Row actions (view, edit, reject, etc.) live in a fixed-width action column on the right, revealed as icon buttons on hover (desktop) or always visible (touch/mobile).
- Status is always a colored chip/badge with text inside it (not a bare colored dot) — text + color together, per the color-blind-safe rule in Section 9.
- Pagination, not infinite scroll, for admin tables — admins need to reference "page 3 of 12," not lose their place in an endless list.

---

## 11. Modals & Overlays

- Width: 480px (simple confirm/form), 720px (multi-field form), 960px max (rare, complex flows like offer generation). No modal wider than 960px — if content needs more room, it's a full page, not a modal.
- Always dismissible via Esc, an explicit close (×) button, and a click on the scrim — except destructive confirmation modals, which require an explicit button choice (no scrim-dismiss on "Reject candidate" type confirmations, to prevent accidental loss).
- One primary + one secondary action in the modal footer, right-aligned, primary rightmost.

---

## 12. Motion

Hard limits — do not exceed:
- Duration: **150ms** for micro-interactions (hover, focus, toggle), **200–250ms** for panel/modal open-close, **300ms max** for any page-level transition. Nothing in the product animates longer than 300ms.
- Easing: `ease-out` for entrances, `ease-in` for exits. No bounce, spring, or elastic easing anywhere in an admin/data product.
- Only ONE orchestrated multi-element animation is allowed in the entire product (e.g., a single onboarding/first-load sequence, if one exists). Everywhere else, motion responds to a user action (open, expand, confirm, error shake) — never plays automatically on scroll or on page load as decoration.
- Respect `prefers-reduced-motion`: all non-essential motion must be disabled or reduced to an opacity crossfade when the user has this set.
- No skeleton-loading shimmer animations longer than 1.2s per cycle; prefer simple static skeletons over shimmering ones if in doubt.

---

## 13. States: Empty, Loading, Error

- Empty states: one line stating what's missing, one line (or button) stating the action to fix it. No decorative illustration required — a simple icon (per Section 9 rules) is enough.
- Loading: skeleton screens for content that takes >300ms, not spinners, for anything list/table-shaped. Spinners are reserved for button-level in-progress states (e.g., "Sending offer…" inside the button itself).
- Errors speak in the system's voice, state what happened and how to recover, never apologize, never say just "Something went wrong" without a next step.

---

## 14. Accessibility Floor (non-negotiable, every screen)

- Visible keyboard focus ring on every interactive element (use the Teal focus ring from Section 6, don't suppress with `outline: none` without a replacement).
- Color contrast: body text on background meets WCAG AA (4.5:1); this rules out light-Indigo-on-Off-White text — check contrast whenever a new color pairing is introduced.
- Every icon-only control has an accessible label (Section 7).
- Tab order follows visual/reading order; no positive `tabindex` values.
- All status/state information (pass/fail, stage, priority) is conveyed by shape/icon/text, not color alone.

---

## 15. Explicitly Forbidden (generic-AI-design tells — do not ship these)

- Warm cream background with terracotta/clay accent, or near-black background with a single neon accent — Aptus's palette is fixed per Section 1.
- Identical rounded cards everywhere with the same soft grey shadow and no hierarchy — Section 2 fixes exactly two radii and two shadow depths for a reason.
- Tracked-out ALL-CAPS eyebrow labels above every heading.
- Meta strings joined with middle dots ("A · B · C") or em-dash labels ("STAGE — Screening").
- A monospace font for small data labels when the rest of the UI is sans-serif.
- Appending "→" to every link/button label.
- Numbered step markers (01 / 02 / 03) on content that isn't actually a sequence.
- Fade-and-slide-up entrance animation on every section as the page loads, or hover-lift on every single card.

---

## 16. Pre-ship Checklist (Codex & Antigravity should self-verify before calling a screen done)

- [ ] Colors used are only the tokens in Section 1, no ad-hoc hex values.
- [ ] Spacing values are all multiples of 8px.
- [ ] Only 2 border-radius values, only 2 shadow depths present on the screen.
- [ ] Icons: single library, only 16px/20px sizes used.
- [ ] Buttons: correct variant count, one Primary per view.
- [ ] All interactive elements have visible focus states and accessible labels.
- [ ] Any animation used is ≤300ms, `ease-out`/`ease-in`, and responds to a user action (not autoplay decoration).
- [ ] Screen tested/usable at the relevant minimum breakpoint (1024px admin / 375px candidate-facing).
- [ ] No item from Section 15's forbidden list appears anywhere on the screen.

---

# Aptus — STRICT Design Guardrails for Antigravity

This is a compliance document, not a style guide. Every rule below exists because Antigravity has already produced the violation it forbids — see "Observed violation" under each rule. Antigravity must check its own output against this list before presenting any screen and must not proceed if a rule is broken.

---

## 0. Two systemic failures to fix first

**A. Overuse of the "numbered sequence" pattern.**
Antigravity currently applies 01/02/03/04 numbering, eyebrow labels, and step-card layouts to content that is not a step-by-step process — landing page value props, feature lists, trust statements — turning every section of the page into a fake "process."

**Observed violation (screenshot):** the homepage uses this pattern FOUR separate times in one page — "Your application journey" (01–04, legitimate, it's an actual sequence), then "A clearer process" (01/02/03, NOT a sequence, it's three unrelated value props), then "Clarity at every stage" (01/02 again, NOT a sequence, it's two unrelated benefits). Three of the four instances are misuse.

**Rule:** Numbered markers (01/02/03…) are permitted in **exactly one place per page**: the single section that represents a genuine ordered sequence the user follows in that order (e.g., the actual application-journey steps). Every other section — value props, feature grids, trust points, benefit callouts — uses a **plain heading + body text, or an icon + heading + body**, never a number. If Antigravity is unsure whether content is a real sequence, the test is: *would it still make sense if reordered?* If yes, it is not a sequence — no numbers.

**B. Tracked-out ALL-CAPS eyebrow labels on every section.**
**Observed violation (screenshot):** "YOUR NEXT STEP, MADE CLEAR," "YOUR APPLICATION JOURNEY," "A CLEARER PROCESS," "CLARITY AT EVERY STAGE," "01 / STAY INFORMED," "02 / KEEP MOVING" — six eyebrow-style labels on one page, several combining caps with a slash-delimited number.

**Rule:** Maximum **ONE** all-caps eyebrow label per page, and only above the hero. Every other section heading is sentence case, no label above it, no slash-number prefix. If a section needs to be introduced, the heading itself does that job — it does not need a caption above it.

---

## 1. Forbidden verbatim patterns (do not reproduce, in any wording)

- Any heading formatted as `NN / WORD` or `NN/ WORD` (e.g., "01 / STAY INFORMED"). This is banned outright, not just limited.
- Any button or link with a trailing arrow glyph (`→`, `↗`) UNLESS it opens something in a new context (external link, new tab) — "Explore open roles ↗" is fine only if it truly navigates elsewhere; "Already applied? Sign in →" is not, remove the arrow.
- Three-line stacked hero headlines where only the last line is colored/accented and the rest is neutral-colored ("Good potential. / The right opportunity. / **Find the fit.**"). This exact pattern — build tension over 2 neutral lines, resolve in 1 accented line — is banned. If the hero needs emphasis, emphasize one phrase inline, once, not a whole final line.
- Hairline horizontal dividers used purely as page-section separators with no content relationship (the thin rule between "A clearer process" and "Clarity at every stage" in the screenshot). Section spacing (Section 3 below) replaces dividers; a divider is only allowed inside a single component (e.g., separating a card's footer from its body).
- Small caps checkmark micro-copy under the CTA ("✓ Your assessments, interviews, and updates.") as a recurring trust-line pattern — allowed once on the whole site maximum, not as a reusable component.

---

## 2. Cross-page consistency (hard requirement)

Antigravity must build and reuse **one shared component library** — it must not re-derive button styles, card styles, heading treatments, or spacing per page. Concretely:

- Before building any new page, Antigravity must list which existing components from prior pages it is reusing, and which (if any) are genuinely new. A page with zero reused components from the existing set is not acceptable — flag it and ask before proceeding.
- The following must be **pixel-identical** across every page they appear on: top bar, sidebar (admin), button styles (per Section 7 of the base instructions), input styles, card style, badge/chip style, footer.
- Heading treatment (weight, size, color) for a given heading level (H1, H2, H3) must be identical across all pages — a page cannot invent its own H2 style because it "felt right" for that page's content.
- Section spacing must follow one rhythm site-wide: 96px between major sections on desktop, 64px on tablet, 48px on mobile — not decided per page.
- Before marking any page complete, Antigravity must do a side-by-side self-check against one already-approved page and confirm: same top bar, same button component, same type scale, same spacing rhythm, same color usage pattern. Any difference must be justified in one sentence or fixed.

---

## 3. Section anatomy (replaces numbered/eyebrow pattern for non-sequential content)

For any section that is NOT a real sequence, use this structure only:
```
[Optional single icon, 24px, one color from the accent set]
Heading (sentence case, H2 or H3 per hierarchy — no eyebrow above it)
One to two lines of supporting body text.
```
No number, no all-caps label, no slash-delimited prefix, no divider above it. Sections are separated by whitespace (per the spacing rhythm in Section 2), not by rules or lines.

---

## 4. Hero section (landing/marketing pages only)

- One headline, maximum 2 lines, sentence case, single consistent color (Indigo or Charcoal) — no line-by-line color escalation.
- If emphasis is needed, apply it to one short phrase inline (color or weight), not an entire line.
- One eyebrow label maximum, and only here (per Section 0B).
- One primary CTA (Teal, per base button rules) + one tertiary text link beside it, maximum — matches the base instructions' one-primary-action rule.
- Supporting paragraph: 2–3 sentences max, sentence case, no bullet-ified trust line beneath it as a recurring pattern (Section 1's last bullet).

---

## 5. Enforcement checklist — run this before showing ANY page

- [ ] Count all-caps eyebrow labels on this page. Is it 0 or 1? (Must not exceed 1, and only above hero.)
- [ ] Count numbered-sequence sections (01/02/03 style) on this page. Is it 0 or 1? Does that one section actually represent an ordered process a user follows in order?
- [ ] Search the page for any `NN / WORD` or `NN/WORD` heading format. Must be zero.
- [ ] Search for trailing arrow glyphs on buttons/links that don't open a new context. Must be zero.
- [ ] Is the hero headline single-color, not escalating color line by line?
- [ ] Are all shared components (top bar, sidebar, buttons, cards, inputs, badges) pixel-identical to the already-approved reference page? If not, stop and reconcile before proceeding.
- [ ] Does every non-sequential section follow the plain heading + body structure in Section 3, with no divider above it?

If any box fails, Antigravity fixes it before presenting the page — it does not present the violation and ask the user to point it out, since this document exists specifically so that doesn't happen again.
