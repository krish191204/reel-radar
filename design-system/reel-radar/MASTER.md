# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** Reel Radar
**Generated:** 2026-07-30 15:33:11
**Last revised:** 2026-08-04
**Category:** Productivity Tool
**Design Dials:** Variance 5/10 (Editorial) | Motion 1/10 (Minimal) | Density 4/10 (Airy)

---

## Signature

The signature is **editorial cinema**: warm bone paper, near-black ink, hairline rules,
large numerical figures, and one decisive vermilion accent. The interface should feel like
a film journal or a Criterion essay index rather than a software dashboard.

The composition carries the identity. Use asymmetry, deliberate negative space, compact
metadata, and strong typographic hierarchy. Posters and film titles remain the visual
subject; application chrome stays quiet.

Vermilion marks active state, primary action, focus, and the most important figure. It is
not decorative color. Teal is a rare cool counterweight and may appear no more than twice
per page.

---

## Global Rules

### Color Palette

The shipped experience is light mode. Surfaces progress through warm paper tones; text,
rules, and hierarchy use ink. Do not introduce additional semantic accent families.

| Role | Hex | CSS Variable | Notes |
|------|-----|--------------|-------|
| Page background | `#F2EFE8` | `--paper` | Warm bone; default canvas |
| Section surface | `#E8E2D5` | `--paper-2` | Rails and grouped regions |
| Card surface | `#DCD5C5` | `--paper-3` | Reserved for contained elements |
| Primary foreground | `#1A1A1A` | `--ink` | Headings, body, rules |
| Secondary foreground | `#3A352E` | `--ink-soft` | Supporting copy |
| Tertiary foreground | `#6B6358` | `--ink-muted` | Labels, captions, metadata |
| Primary accent | `#D63838` | `--vermilion` | CTA, active, focus, key figure |
| Accent pressed | `#A12828` | `--vermilion-deep` | Hover and pressed state |
| Accent tint | `#F5DADA` | `--vermilion-soft` | Quiet selected surface |
| Cool counterweight | `#1F3A3A` | `--teal` | Maximum two uses per page |

**Color discipline**

- Default to paper and ink; color must communicate priority or state.
- Use vermilion for one primary action or focal datum within a region.
- Never use teal as a second general-purpose accent.
- Use ink at reduced visual weight through the provided foreground tokens, not arbitrary gray.
- Hairline rules use ink with restrained opacity or an established border token.
- Avoid gradients, glows, glass effects, neon, and saturated multicolor category systems.
- Posters retain their native color; surrounding UI must not compete with them.

**Focus ring:** use a visible `2px` vermilion outline with sufficient offset from the
component edge. Focus must remain legible on all three paper surfaces and must never rely
on color fill alone.

### Typography

- **Display:** Fraunces 600/700
- **Body:** Inter 400/500/600/700
- **Mono:** IBM Plex Mono 400/500/600

**Scoped display usage:** Fraunces applies only to `.rr-brand` and `.rr-panel-title`.
Do not apply it globally to heading elements or Streamlit widget labels. Editorial impact
comes from scale and spacing, not from using the display face everywhere.

Use Inter for titles, controls, paragraphs, navigation, empty states, and ticket names.
Use IBM Plex Mono for numerical figures, ranks, scores, labels, compact metadata, and
chart annotations.

```css
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap');
```

**Type hierarchy**

- Brand and panel titles: Fraunces, compact leading, editorial scale.
- Page title: Inter 700; large but not ornamental.
- Ticket title: Inter 600/700; one clear reading line where practical.
- Body copy: Inter 400; comfortable line height and a readable measure.
- Eyebrow, metadata, rank, score: IBM Plex Mono; compact and restrained.
- Large figures: IBM Plex Mono or Inter 700; use tabular numerals where comparison matters.
- Labels are sentence case or concise uppercase mono; avoid title case on every control.

### Spacing Variables

*Density: 4/10 — Airy editorial composition*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` | Tight label and metadata gaps |
| `--space-sm` | `8px` | Inline spacing |
| `--space-md` | `16px` | Standard component padding |
| `--space-lg` | `24px` | Panel and card padding |
| `--space-xl` | `32px` | Grid and section gaps |
| `--space-2xl` | `48px` | Major section separation |
| `--space-3xl` | `64px` | Editorial breathing room |

Prefer fewer containers with more internal space. Align content to a consistent page grid.
Do not fill empty space merely to make a section feel complete.

### Borders and Depth

Hairline rules are the primary separator. Use `1px` borders and structural whitespace
before reaching for shadows.

- Default border: ink at low opacity.
- Strong divider: solid ink, `1px`.
- Active edge: `2px` vermilion where specified.
- Empty-state boundary: `1px dashed` muted ink.
- Border radius: restrained; pills are reserved for compact actions and tags.
- Shadows: rare, soft, and shallow. Tickets and panels should usually remain flat.

---

## Component Specs

### Empty State

`.rr-empty` is a quiet editorial placeholder with a dashed boundary, generous padding,
and a short path forward. It should never resemble an error alert.

- Title: Inter 600, ink.
- Supporting copy: Inter 400, ink-soft, readable width.
- Boundary: dashed ink-muted rule on paper or paper-2.
- Alignment: left by default; center only in a narrow isolated region.
- Keep copy to one title and one brief explanation.

The optional `.rr-empty-cta` is a compact vermilion pill for navigation to the action
that unblocks the state. Use white or paper text with verified contrast, a small directional
icon, and a visible focus ring. It is not a generic tag and must not multiply within one
empty state.

### Top Nav

`.rr-topnav` is the global navigation and replaces framework-provided sidebar navigation.
It sits at the top of the content flow with a hairline rule beneath it.

- Brand sits at the leading edge; page links follow in a stable order.
- Active link uses a vermilion underline, not a filled tab.
- Inactive links use ink-soft and become ink on hover.
- Navigation remains light, flat, and free of drop shadows.
- Preserve keyboard order, visible focus, and a minimum practical hit target.
- On small screens, wrap or simplify without introducing horizontal page scroll.
- Keep `client.showSidebarNavigation = false`; do not expose duplicate navigation.

### Mode Tiles

`.rr-tile` presents the eight modes in a `4 × 2` desktop grid within the left side of the
Home composition. Tiles are editorial entry points, not dashboard cards.

- Surface: paper or paper-2 with a fine ink rule.
- Active tile: vermilion top border and a restrained selected treatment.
- Title: Inter 600/700; description: ink-muted; optional index: mono.
- Keep icons minimal and from one SVG family when needed.
- Hover may adjust border or text color; avoid scaling and pronounced elevation.
- Collapse responsively to two columns, then one column when space requires it.
- Entire interactive tile receives pointer cursor and one accessible label.

### Right Rail

`.rr-rail` is the right column of Home: a paper-2 editorial panel that summarizes taste or
catalog context without becoming a conventional analytics dashboard.

- Lead with one large vermilion figure and a short mono label.
- Separate groups with hairline rules and meaningful whitespace.
- Use compact custom bars for comparisons.
- Supporting values use ink, ink-soft, and ink-muted hierarchy.
- Teal may mark one cool counterpoint, subject to the page-wide two-use limit.
- The rail may stack below mode tiles on narrow viewports.
- Avoid KPI-card grids, boxed mini-panels, gauges, and chart chrome.

### Ticket Card

`.rr-ticket` is a minimal recommendation unit containing poster, title, and concise metadata.
The card exists to support film recognition and selection, not to explain the full model.

- Poster is the primary image and keeps its natural aspect ratio.
- Title is Inter 600/700 and remains visually adjacent to the poster.
- Metadata uses IBM Plex Mono or compact Inter in ink-muted.
- Use a hairline boundary or spacing; avoid heavy shadow and ornamental framing.
- Do not include a role pill or explanatory reason paragraph in the base ticket.
- Card hover is subtle: border, underline, or small color shift without layout movement.
- Ticket action and detail disclosure must be keyboard accessible.
- Long titles truncate or wrap predictably without shifting neighboring cards.

### Popover Breakdown

`.rr-popover-breakdown` contains the model explanation on demand, keeping the ticket itself
minimal. It displays signed contributions as horizontal bars around a shared centerline.

- Positive values extend right of center; negative values extend left.
- Normalize widths against the largest absolute value in the displayed set.
- Use vermilion for the emphasized positive direction and ink/teal sparingly elsewhere.
- Include labels and numerical values; color and direction alone are insufficient.
- Keep labels human-readable and stable across recommendation modes.
- Popover must support keyboard opening, Escape dismissal, focus return, and viewport bounds.
- Avoid animation beyond the global entry behavior.

### Custom Bars

`.rr-rail-bars` is the required pattern for small distributions and comparisons. It replaces
framework chart widgets and preserves the editorial visual language.

- Build bars with semantic HTML and CSS, not a general chart component.
- Use a shared scale for values intended for comparison.
- Place concise labels and values in mono text.
- Track uses paper-3 or low-opacity ink; fill uses ink by default.
- Reserve vermilion for the highlighted or active datum.
- Use teal only as the limited cool counterweight.
- Provide text values and accessible names independent of bar length.
- Avoid axes, legends, tooltips, gradients, rounded capsules, and decorative animation.
- Never use `st.bar_chart`.

---

## Style Guidelines

**Style:** Editorial Cinema (Paper + Ink)

**Keywords:** editorial cinema, warm bone paper, ink, vermilion, hairline rules, large
numbers, asymmetric composition, negative space, film journal, restrained, tactile

**Best For:** Film discovery, criticism, recommendation, curation, and personal taste tools
where posters and editorial content should lead while controls remain quiet.

**Key Effects:** flat paper surfaces, sharp hierarchy, fine rules, one accent, subtle entry,
and carefully paced whitespace. Boldness comes from composition and typography rather than
decoration.

### Page Pattern

**Pattern Name:** Editorial Split + Rail

- **Global order:** Top nav → page heading/context → primary task → supporting detail.
- **Home:** Top nav → two-column composition with mode tiles left and right rail right.
- **Recommendation pages:** Panel title → controls → result tickets → optional breakdown.
- **CTA placement:** Close to the action it advances; one primary CTA per region.
- **Narrow screens:** Stack primary column before the rail and preserve reading order.
- **No Home footer grid:** End when the composition is complete; do not append extra portals.

---

## Motion

**Motion budget: 1 keyframe total.** The only keyframe is `rr-rise`.

**Entry — `rr-rise`:** runs once when relevant page content enters. Use a short upward
translation paired with opacity, restrained distance, and the shared editorial easing.
Stagger only tightly related siblings such as mode tiles or ticket results. Delays must not
make the interface feel sequential or slow.

**Interaction transitions:** color, border-color, background-color, and small opacity
changes may transition for 150–280ms. These are transitions, not additional keyframes.
Avoid scale effects and noticeable card lift.

**No ambient motion:** no pulsing, shimmer, scanning, floating, looping, animated grain,
or autoplay decoration. Data bars render at their final widths.

**Reduced motion:** under `prefers-reduced-motion: reduce`, disable `rr-rise`, remove
nonessential smooth scrolling, and make state changes immediate while preserving clarity.

---

## Anti-Patterns (Do NOT Use)

- Dark application chrome or dark-mode-first styling.
- More than one general accent color.
- Colorful dashboard card grids or generic SaaS KPI rows.
- Framework sidebar navigation or duplicate page navigation.
- Framework bar charts or mismatched visualization chrome.
- Large filled navigation tabs when an underline communicates active state.
- Heavy shadows, glassmorphism, gradients, glows, or excessive rounded cards.
- Decorative motion, looping animation, or multiple entry effects.
- Dense layouts that erase editorial negative space.
- Extra mode portal sections appended below the Home composition.
- Multi-cell taste-summary ribbons.
- Explanation paragraphs or role pills inside minimal tickets.
- Emoji used as interface icons; use a consistent SVG icon family.
- Layout-shifting hover effects or scale transforms.
- Invisible focus states, color-only state, or low-contrast muted text.
- Clickable elements without pointer cursor or keyboard behavior.
- Raw colors where an established design token exists.

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] Light mode is the shipped default and all surfaces use the paper scale.
- [ ] Palette is limited to paper, ink, vermilion, and tightly constrained teal.
- [ ] Text and interactive controls meet WCAG contrast requirements.
- [ ] Fraunces is scoped to `.rr-brand` and `.rr-panel-title` only.
- [ ] Inter is the body and interface face; IBM Plex Mono handles data and metadata.
- [ ] Top navigation is present, active state has a vermilion underline, and sidebar nav is hidden.
- [ ] Home uses the two-column mode-tile and right-rail composition.
- [ ] Mode tiles resolve from `4 × 2` to accessible smaller-screen layouts.
- [ ] Empty states include a useful next step and at most one CTA pill.
- [ ] Tickets contain poster, title, and metadata without extra explanatory clutter.
- [ ] Detailed score explanations live in the accessible popover breakdown.
- [ ] All bar displays use custom editorial HTML/CSS bars, never `st.bar_chart`.
- [ ] Hairline rules and spacing provide structure before shadows or containers.
- [ ] Vermilion marks only meaningful action, focus, active state, or focal data.
- [ ] Teal appears no more than twice on a page.
- [ ] No emojis are used as icons; SVG icons come from one consistent family.
- [ ] Clickable elements have pointer cursor, keyboard behavior, and visible focus.
- [ ] Hover states do not shift layout and transitions remain within 150–280ms.
- [ ] `rr-rise` is the only keyframe and is disabled for reduced-motion users.
- [ ] Responsive behavior is checked at 375px, 768px, 1024px, and 1440px.
- [ ] No horizontal scroll or content hidden behind navigation appears on mobile.
- [ ] Posters preserve aspect ratio, useful alt text, and stable layout dimensions.
- [ ] Empty, loading, populated, error, hover, focus, and selected states are legible.
- [ ] The final page reads as editorial cinema, not a generic analytics dashboard.
