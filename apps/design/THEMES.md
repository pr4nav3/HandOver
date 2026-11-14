# HandOver themes

14 themes in four groups: Classic, Grain, Color, Mono. Each theme has every color role from [DESIGN.md](DESIGN.md) section 2.1, exact hex values, grain settings where used, and measured contrast for text roles.

## Where these come from

- The color values are Vibeflux's (`vibeflux/Sources/Design/DeckThemeCatalog.swift`, `DeckThemeTokens`). Vibeflux's `DeckThemeContrastTests` already checks each of them against the full WCAG AA pair matrix (`contrastProblems()`), on Mac, iPhone and Android (`Contrast.problems` in `DeckTheme.kt`). HandOver reuses them so the contrast is proven, not hoped for.
- The grouping, the true-black theme, the High Contrast 7:1 target and the "Mono means no hue, status keeps meaning through words and symbols" rule come from Glasspad (`glasspad/Packages/GlasspadKit/Sources/GlasspadKit/Theme/ThemeCatalog.swift`) and Vibeflux.
- Grain method: Vibeflux `DeckGrain.texture(.grain, amount:dark:)`, see DESIGN.md 2.7.

## Rules

- Stored ids are the left column in the catalog table and never change (they may sync between devices).
- A theme either follows the system light or dark setting with its two looks, or keeps one look always.
- A separate Appearance setting (System, Light, Dark) applies to themes with two looks, so picking Dark never throws away the theme. From `DeckAppearance`, `DeckThemeCatalog.swift`.
- Roles shared by every theme (not repeated below): `stage` `#000000`, `captionFill` `#000000` at 72%, `captionInk` `#FFFFFF`, `record` `#D70015`.
- Derived roles (not repeated below): `accentSoft` = `accent` at 12% (light) or 16% (dark). Hover = `ink` at 5% light, white at 6% dark. Pressed = `ink` at 9% light, white at 10% dark. Tone washes = tone at 12% or 16%.
- `line` and `lineStrong` are `ink` at the given alpha in light looks and `#FFFFFF` at the given alpha in dark looks, unless a theme says otherwise.
- Defaults when a theme does not list them. Light: `good` `#186629`, `caution` `#934000`, `bad` `#B80011`, `idle` `#6E6E73`, `line` 9%, `lineStrong` 16%. Dark: `good` `#30D158`, `caution` `#FF9F0A`, `bad` `#FF6961`, `idle` `#8E8E93`, `line` 10%, `lineStrong` 17%.

## How contrast was measured

WCAG 2.x relative luminance and ratio `(L1 + 0.05) / (L2 + 0.05)`. Roles with alpha (`ink2`, `ink3`) are composited over the surface in sRGB first, the way `DeckRGB.over` does. Grain themes are measured on the worst grain pixel: paper dipped by the grain amount for dark text, lifted for light text. Ratios below are rounded down to one decimal. Requirement: 4.5 for text, 3.0 for marks; High Contrast aims for 7.0.

The full matrix (every tone on its own wash, `ink3` at 3:1, `idle` at 3:1, the accent fill at 3:1 on every surface) is enforced by the ported contrast test, not repeated here.

## Catalog

| Id | Name | Group | Looks | One line for the picker |
|---|---|---|---|---|
| `system` | Default | Classic | follows system | Cool gray, HandOver blue |
| `night` | Night | Classic | always dark | True black for OLED |
| `highContrast` | High Contrast | Classic | follows system | Firmer text and edges |
| `ivory` | Ivory | Classic | follows system | Cream and ink blue |
| `dim` | Dim | Classic | always dark | Gentle dark slate |
| `grain` | Grain | Grain | follows system | Paper with a fine grain |
| `newsprint` | Newsprint | Grain | always light | Gray stock, red ink |
| `chalkboard` | Chalkboard | Grain | always dark | Chalk on green |
| `harbor` | Harbor | Color | follows system | Cool teal |
| `sage` | Sage | Color | follows system | Muted green |
| `clay` | Clay | Color | follows system | Terracotta |
| `nocturne` | Nocturne | Color | always dark | Navy, always dark |
| `mono` | Mono | Mono | follows system | Black and white |
| `matte` | Matte | Mono | always light | Gray, low glare |

That covers light (Default light, Ivory, Grain light, Newsprint, Harbor, Sage, Clay, Mono light, Matte), dark (Default dark, Dim, Grain dark, Chalkboard, Nocturne and the dark looks), true black (Night, High Contrast dark, Mono dark), grainy (Grain, Newsprint, Chalkboard) and mono (Mono, Matte).

Default for new installs: `system`. With the system setting Increase Contrast on, the app uses `highContrast` values in the current appearance without changing the stored choice.

---

## Classic

### Default (`system`)

| Role | Light | Dark |
|---|---|---|
| paper | `#F0F1F2` | `#131416` |
| raised | `#FBFBFC` | `#1D1E21` |
| well | `#E4E5E8` | `#26272B` |
| ink | `#1A1B1E` | `#EDEEF0` |
| ink2 | ink at 70% | ink at 68% |
| ink3 | ink at 50% | ink at 46% |
| line, lineStrong | 9%, 16% | 10%, 17% |
| accent | `#3E5FD9` | `#8AA8FF` |
| onAccent | `#FFFFFF` | `#0E1630` |
| accentInk | `#3249B8` | `#8AA8FF` |
| good, caution, bad, idle | defaults | defaults |
| grain | none | none |

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 15.2 | 15.8 |
| ink2 on paper | 5.9 | 7.7 |
| ink2 on raised | 6.2 | 7.3 |
| accentInk on raised | 7.3 | 7.2 |
| onAccent on accent | 5.4 | 7.7 |
| good on paper | 6.2 | 9.1 |
| caution on paper | 6.2 | 8.9 |
| bad on paper | 6.1 | 6.5 |

### Night (`night`), always dark, true black

| Role | Value |
|---|---|
| paper | `#000000` |
| raised | `#0F0F11` |
| well | `#1C1C1F` |
| ink | `#F2F2F4` |
| ink2, ink3 | ink at 66%, 44% |
| line, lineStrong | white 12%, 20% |
| accent, accentInk | `#8AA8FF` |
| onAccent | `#0E1630` |
| good, caution, bad, idle | dark defaults |

| Pair | Ratio |
|---|---|
| ink on paper | 18.7 |
| ink2 on paper | 8.0 |
| ink2 on raised | 7.7 |
| accentInk on raised | 8.3 |
| onAccent on accent | 7.7 |
| good, caution, bad on paper | 10.3, 10.2, 7.4 |

### High Contrast (`highContrast`)

| Role | Light | Dark |
|---|---|---|
| paper | `#FFFFFF` | `#000000` |
| raised | `#F2F2F4` | `#1A1A1C` |
| well | `#E3E3E8` | `#2A2A2E` |
| ink | `#000000` | `#FFFFFF` |
| ink2, ink3 | 84%, 66% | 86%, 66% |
| line, lineStrong | 42%, 66% | 45%, 70% |
| accent, accentInk | `#0030C0` | `#ADC4FF` |
| onAccent | `#FFFFFF` | `#00102E` |
| good | `#0B5E25` | `#6CF294` |
| caution | `#7A3300` | `#FFC46B` |
| bad | `#A3000E` | `#FF8A80` |
| idle | `#5E5E62` | `#B4B4B8` |

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 21.0 | 21.0 |
| ink2 on paper | 14.5 | 15.1 |
| ink2 on raised | 13.4 | 13.0 |
| accentInk on raised | 8.5 | 10.0 |
| onAccent on accent | 9.6 | 10.8 |
| good on paper | 7.9 | 14.7 |
| caution on paper | 9.1 | 13.3 |
| bad on paper | 8.0 | 9.2 |

Every text pair is 7.0 or more.

### Ivory (`ivory`)

| Role | Light | Dark |
|---|---|---|
| paper | `#F4F1EA` | `#1A1815` |
| raised | `#FCFBF7` | `#24211D` |
| well | `#E9E5DB` | `#2E2A25` |
| ink | `#221E18` | `#EFEAE0` |
| ink2, ink3 | 70%, 50% | 68%, 46% |
| accent | `#255EA8` | `#95B7EE` |
| onAccent | `#FFFFFF` | `#0E1A30` |
| accentInk | `#1F4F8E` | `#95B7EE` |
| bad | default | `#FF7A70` |
| other tones | defaults | defaults |

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 14.6 | 14.7 |
| ink2 on paper | 5.7 | 7.3 |
| ink2 on raised | 6.0 | 6.9 |
| accentInk on raised | 7.9 | 7.8 |
| onAccent on accent | 6.4 | 8.5 |
| good, caution, bad on paper | 6.2, 6.2, 6.1 | 8.7, 8.6, 6.9 |

### Dim (`dim`), always dark

| Role | Value |
|---|---|
| paper | `#1F2227` |
| raised | `#272A30` |
| well | `#30343A` |
| ink | `#E1E4E8` |
| ink2, ink3 | 72%, 50% |
| accent, accentInk | `#93ACF2` |
| onAccent | `#101830` |
| bad | `#FF8A82` |
| idle | `#9696A0` |
| good, caution | dark defaults |

| Pair | Ratio |
|---|---|
| ink on paper | 12.5 |
| ink2 on paper | 7.1 |
| ink2 on raised | 6.5 |
| accentInk on raised | 6.4 |
| onAccent on accent | 7.8 |
| good, caution, bad on paper | 7.8, 7.7, 7.0 |

---

## Grain

Grain is drawn on `paper` only (DESIGN.md 2.7). Tile: 128 px, seed `0x6465636B67726169`, alpha per pixel `abs(n) * 2 * amount * 2.2`. "Amount" is how far the worst pixel moves brightness either way (0 to 1 of full scale). Scale: one tile pixel per device pixel, so grain is 1 px on every screen (about a third of a point on a 3x iPhone).

### Grain (`grain`)

| Role | Light | Dark |
|---|---|---|
| paper | `#EEEDE9` | `#171716` |
| raised | `#FAFAF8` | `#21211F` |
| well | `#E3E2DD` | `#2B2B29` |
| ink | `#1C1B19` | `#EEEDEA` |
| ink2, ink3 | 72%, 52% | 70%, 48% |
| accent, accentInk | `#34519F` | `#9DB1F2` |
| onAccent | `#FFFFFF` | `#111A33` |
| bad | `#A8000F` | default |
| other tones | defaults | defaults |
| grain amount | 0.030 | 0.025 |
| worst paper sample | `#E6E5E1` (dipped) | `#1D1D1C` (lifted) |

| Pair (paper pairs on the worst sample) | Light | Dark |
|---|---|---|
| ink on paper | 13.6 | 14.4 |
| ink2 on paper | 6.0 | 7.6 |
| ink2 on raised | 6.7 | 7.4 |
| accentInk on raised | 7.1 | 7.6 |
| onAccent on accent | 7.4 | 8.2 |
| good, caution, bad on paper | 5.6, 5.6, 6.2 | 8.3, 8.2, 6.0 |

### Newsprint (`newsprint`), always light

| Role | Value |
|---|---|
| paper | `#E8E6E1` |
| raised | `#F5F4F0` |
| well | `#DCDAD4` |
| ink | `#141414` |
| ink2, ink3 | 74%, 54% |
| accent | `#A3221E` |
| onAccent | `#FFFFFF` |
| accentInk | `#961E1A` |
| good, caution, bad, idle | `#155C25`, `#843900`, `#9E000F`, `#626266` |
| grain amount | 0.035 |
| worst paper sample | `#DFDDD8` |

| Pair | Ratio |
|---|---|
| ink on paper | 13.5 |
| ink2 on paper | 6.6 |
| ink2 on raised | 7.5 |
| accentInk on raised | 7.6 |
| onAccent on accent | 7.4 |
| good, caution, bad on paper | 5.9, 6.0, 6.2 |

Note: the accent is red, so the mistake card (caution) and the accent never meet on one control. Destructive buttons in this theme also carry the `trash` symbol so they are not read as primary.

### Chalkboard (`chalkboard`), always dark

| Role | Value |
|---|---|
| paper | `#1D2A25` |
| raised | `#24332D` |
| well | `#2C3C36` |
| ink | `#EEF2EC` |
| ink2, ink3 | 74%, 52% |
| line, lineStrong | white 12%, 20% |
| accent, accentInk | `#F0E19A` |
| onAccent | `#2A2600` |
| good, caution, bad, idle | `#7CF0A0`, `#FFC071`, `#FF9C93`, `#A3B0AA` |
| grain amount | 0.030 |
| worst paper sample | `#25322D` (lifted) |

| Pair | Ratio |
|---|---|
| ink on paper | 11.7 |
| ink2 on paper | 7.2 |
| ink2 on raised | 7.1 |
| accentInk on raised | 10.0 |
| onAccent on accent | 11.5 |
| good, caution, bad on paper | 9.4, 8.2, 6.6 |

---

## Color

### Harbor (`harbor`)

| Role | Light | Dark |
|---|---|---|
| paper | `#ECF0F1` | `#0F1619` |
| raised | `#F9FBFB` | `#172024` |
| well | `#DEE5E7` | `#202B30` |
| ink | `#15202A` | `#E6EEF1` |
| ink2, ink3 | 72%, 50% | 70%, 46% |
| accent | `#0F6680` | `#6CC4DB` |
| onAccent | `#FFFFFF` | `#06222B` |
| accentInk | `#0B5A71` | `#6CC4DB` |
| tones | defaults | defaults |

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 14.3 | 15.5 |
| ink2 on paper | 6.1 | 8.0 |
| ink2 on raised | 6.4 | 7.5 |
| accentInk on raised | 7.4 | 8.3 |
| onAccent on accent | 6.4 | 8.3 |
| good, caution, bad on paper | 6.1, 6.1, 6.0 | 9.0, 8.9, 6.4 |

### Sage (`sage`)

| Role | Light | Dark |
|---|---|---|
| paper | `#EEF1EC` | `#141814` |
| raised | `#FAFBF8` | `#1C221C` |
| well | `#E1E6DE` | `#252C25` |
| ink | `#1A211B` | `#E7EEE6` |
| ink2, ink3 | 72%, 50% | 70%, 46% |
| accent | `#3E6B48` | `#9CCB9F` |
| onAccent | `#FFFFFF` | `#10241A` |
| accentInk | `#345C3D` | `#9CCB9F` |
| tones | defaults | defaults |

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 14.4 | 15.1 |
| ink2 on paper | 6.1 | 7.8 |
| ink2 on raised | 6.3 | 7.3 |
| accentInk on raised | 7.3 | 8.8 |
| onAccent on accent | 6.1 | 8.8 |
| good, caution, bad on paper | 6.2, 6.2, 6.0 | 8.8, 8.7, 6.3 |

Note: the accent is green, near `good`. Verified uses the `checkmark.circle.fill` symbol and the word, so it never depends on hue here.

### Clay (`clay`)

| Role | Light | Dark |
|---|---|---|
| paper | `#F3EEEA` | `#1B1513` |
| raised | `#FCFAF8` | `#251D1A` |
| well | `#E8E0D9` | `#2F2622` |
| ink | `#241B17` | `#F2E9E4` |
| ink2, ink3 | 72%, 50% | 70%, 46% |
| accent | `#A8452A` | `#F0A07E` |
| onAccent | `#FFFFFF` | `#2E1208` |
| accentInk | `#963C22` | `#F0A07E` |
| tones | defaults | defaults |

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 14.6 | 15.0 |
| ink2 on paper | 6.2 | 7.8 |
| ink2 on raised | 6.5 | 7.3 |
| accentInk on raised | 6.8 | 7.9 |
| onAccent on accent | 5.9 | 8.3 |
| good, caution, bad on paper | 6.1, 6.1, 5.9 | 8.9, 8.7, 6.3 |

### Nocturne (`nocturne`), always dark

| Role | Value |
|---|---|
| paper | `#0E1221` |
| raised | `#151A2D` |
| well | `#1D2339` |
| ink | `#E6E9F5` |
| ink2, ink3 | 70%, 46% |
| accent, accentInk | `#9AAEFF` |
| onAccent | `#101640` |
| tones | dark defaults |

| Pair | Ratio |
|---|---|
| ink on paper | 15.3 |
| ink2 on paper | 7.9 |
| ink2 on raised | 7.5 |
| accentInk on raised | 8.1 |
| onAccent on accent | 8.1 |
| good, caution, bad on paper | 9.2, 9.0, 6.6 |

---

## Mono

No hue anywhere. Every status keeps its meaning through its word and SF Symbol (DESIGN.md 3.1), timeline segments through their numbers, roles through position. From Vibeflux `monoLight` and `monoDark` ("status keeps its meaning through the word or symbol next to it") and Glasspad `isMonochrome`.

In Mono themes the recording color stays `#D70015` and the caption bar stays black: a recording indicator must be unmistakable, and captions sit on video, not on the theme.

### Mono (`mono`)

| Role | Light | Dark |
|---|---|---|
| paper | `#FFFFFF` | `#000000` |
| raised | `#F6F6F6` | `#121212` |
| well | `#EBEBEB` | `#222222` |
| ink | `#000000` | `#FFFFFF` |
| ink2, ink3 | 66%, 46% | 68%, 46% |
| line, lineStrong | 12%, 20% | 14%, 22% |
| accent, accentInk | `#000000` | `#FFFFFF` |
| onAccent | `#FFFFFF` | `#000000` |
| good, bad | `#000000` | `#FFFFFF` |
| caution | `#555555` | `#AAAAAA` |
| idle | `#777777` | `#888888` |

| Pair | Light | Dark |
|---|---|---|
| ink on paper | 21.0 | 21.0 |
| ink2 on paper | 7.2 | 9.3 |
| ink2 on raised | 7.1 | 8.9 |
| accentInk on raised | 19.4 | 18.7 |
| onAccent on accent | 21.0 | 21.0 |
| caution on paper | 7.4 | 9.0 |

The dark look is true black.

### Matte (`matte`), always light

| Role | Value |
|---|---|
| paper | `#E7E6E2` |
| raised | `#F1F0EC` |
| well | `#DBDAD5` |
| ink | `#1E1E1E` |
| ink2, ink3 | 74%, 54% |
| line, lineStrong | 12%, 20% |
| accent, accentInk | `#2E2E2E` |
| onAccent | `#F1F0EC` |
| good, bad | `#1E1E1E` |
| caution | `#4F4F4F` |
| idle | `#6A6A6A` |

| Pair | Ratio |
|---|---|
| ink on paper | 13.3 |
| ink2 on paper | 6.2 |
| ink2 on raised | 6.6 |
| accentInk on raised | 11.9 |
| onAccent on accent | 11.9 |
| caution on paper | 6.5 |

---

## Theme picker

Settings, Appearance. From Vibeflux `AppearanceView` and `DeckThemePicker` (`SettingsView.swift`) and Glasspad's Settings previews (`ThemeChoice.preview(dark:)` in `Theme.swift`).

- Top: Appearance segmented control: System, Light, Dark. Footer: "Themes with one look keep it."
- Then sections Classic, Grain, Color, Mono. Each theme is a card 2 per row on iPhone, 4 on iPad and Mac: a mini preview (paper with a raised card, a line of ink, a line of ink2, an accent pill, grain drawn if the theme has it), drawn with the theme's fixed colors in both looks side by side for themes with two looks, then the name (`bodyMedium`) and the one line (`caption`, `ink2`). Selected: 2 pt `accent` ring of the current theme, `checkmark.circle.fill`.
- Search field: "Search 14 themes". Matches name, one line, group and the keywords: Default "auto automatic", Night "black oled amoled", High Contrast "accessibility contrast bold", Mono "black white grayscale", Matte "eink e-ink grayscale reader".
- Picking applies at once to the whole app, with no animation (a full redraw) and returns to the same scroll position (Vibeflux `RootView.reopenSettings`).
- VoiceOver: each card "Harbor, cool teal, follows system. Selected."
