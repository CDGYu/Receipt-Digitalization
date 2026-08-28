import type { JSX } from 'react'
import { Chip } from './Chip'

/** A confidence score rendered as a banded status chip -- shared by the review
 * queue and the results list so both read the same, and the bands live in one
 * place.
 *
 * ## Five fixed bands, lowest first
 *
 * `0.00-0.20`, `0.21-0.40`, `0.41-0.60`, `0.61-0.80`, `0.81-1.00` -- the owner's
 * even 0.20 buckets for triage, deliberately independent of where the pipeline
 * auto-approves (0.85) or routes to review (0.60). Lowest is the loudest (error
 * tone, a full gauge glyph) because it most needs a human; highest is the
 * calmest (positive, an empty ring). Each band differs by TONE and by how much
 * of its ring is filled, so it reads without colour (§6, never colour alone) --
 * which is also why `Chip` requires both an icon and text.
 *
 * ## No float, ever
 *
 * `confidence` is a `Money`-branded decimal string, and `Number("0.850")` both
 * drops precision (ADR-0001) and trips the repository's no-float guard. The band
 * is chosen by comparing the value against each band's lower bound AS A STRING
 * (:func:`decimalAtLeast`), and the exact string is what the chip shows -- so no
 * precision is invented or lost. A `null` score is the neutral "--" placeholder
 * rather than a guessed band.
 */

/** Whether decimal string `a` is `>=` decimal string `b`, WITHOUT a float.
 *
 * Split each into whole and fraction parts, right-pad the fractions to equal
 * length, and compare the two parts as strings: for equal-length numeric strings
 * lexicographic order IS numeric order. Confidence is always `0.000`..`1.000`
 * here; the parser is still defensive (a missing fraction pads to "0"). */
function decimalAtLeast(a: string, b: string): boolean {
  const [aWhole, aFrac = ''] = a.split('.')
  const [bWhole, bFrac = ''] = b.split('.')
  const width = Math.max(aFrac.length, bFrac.length)
  const aKey = `${aWhole.padStart(3, '0')}.${aFrac.padEnd(width, '0')}`
  const bKey = `${bWhole.padStart(3, '0')}.${bFrac.padEnd(width, '0')}`
  return aKey >= bKey
}

type ChipTone = 'error' | 'warn' | 'info' | 'positive' | 'neutral'

/** A gauge glyph: an outline ring with a pie wedge filled from 12 o'clock
 * clockwise, so each band shows a different amount of "meter" and reads without
 * colour. `fill` is a discrete level 0..5 (fifths of the circle): 5 is a full
 * disc (lowest band, loudest), 0 is a bare ring (highest band).
 *
 * **The wedge is anchored at the circle's centre (10,10)**, not chorded off the
 * bottom, so its optical mass stays centred at every level -- the earlier
 * bottom-weighted chords made the glyph read as sitting low and oversized next
 * to the text. The fill radius is `5` against the ring's `6.25`, so the wedge
 * sits *inside* the stroke with a hairline gap rather than overrunning it, which
 * is what made it look heavy. */
function GlyphGauge({ fill }: { fill: 0 | 1 | 2 | 3 | 4 | 5 }) {
  const CX = 10
  const CY = 10
  const R = 5
  // A pie wedge of `fill` fifths, from the top (12 o'clock) going clockwise.
  // Centre -> top -> arc to the end angle -> back to centre. `null` for empty,
  // and a plain disc for full so no arc degeneracy at 360deg.
  function wedge(level: 1 | 2 | 3 | 4): string {
    const angle = (level / 5) * 2 * Math.PI
    const endX = CX + R * Math.sin(angle)
    const endY = CY - R * Math.cos(angle)
    const largeArc = level / 5 > 0.5 ? 1 : 0
    return `M${CX} ${CY} L${CX} ${CY - R} A${R} ${R} 0 ${largeArc} 1 ${endX.toFixed(3)} ${endY.toFixed(3)} Z`
  }
  const inner =
    fill === 0 ? null : fill === 5 ? (
      <circle cx={CX} cy={CY} r={R} fill="currentColor" stroke="none" />
    ) : (
      <path d={wedge(fill)} fill="currentColor" stroke="none" />
    )
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
      {inner}
    </svg>
  )
}

/** No score to band: a bare ring, the neutral placeholder. */
function GlyphUnknown() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="10" cy="10" r="6.25" />
    </svg>
  )
}

/** The five bands, lowest first -- the order a reviewer works them. `min` is the
 * inclusive lower bound as a decimal string; the band a score falls in is the
 * highest whose `min` it is `>=`. Change a cut point here and both screens shift
 * with it. */
const BANDS: readonly {
  readonly min: string
  readonly tone: ChipTone
  readonly fill: 0 | 1 | 2 | 3 | 4 | 5
  readonly label: string
}[] = [
  { min: '0.81', tone: 'positive', fill: 0, label: '0.81-1.00' },
  { min: '0.61', tone: 'info', fill: 2, label: '0.61-0.80' },
  { min: '0.41', tone: 'neutral', fill: 3, label: '0.41-0.60' },
  { min: '0.21', tone: 'warn', fill: 4, label: '0.21-0.40' },
  { min: '0.00', tone: 'error', fill: 5, label: '0.00-0.20' },
]

function bandFor(confidence: string | null): {
  tone: ChipTone
  icon: JSX.Element
  label: string
  value: string
} {
  if (confidence === null) {
    return { tone: 'neutral', icon: <GlyphUnknown />, label: 'no score', value: '--' }
  }
  const band =
    BANDS.find((candidate) => decimalAtLeast(confidence, candidate.min)) ?? BANDS[BANDS.length - 1]
  return { tone: band.tone, icon: <GlyphGauge fill={band.fill} />, label: band.label, value: confidence }
}

/** Render a confidence score as its banded chip. `null` shows the neutral "--".
 *
 * The exact score leads and the band range follows in parentheses, so a reviewer
 * reads the precise number and sees which bucket the tone and gauge stand for. */
export function ConfidenceChip({ confidence }: { confidence: string | null }) {
  const band = bandFor(confidence)
  return (
    <Chip tone={band.tone} icon={band.icon}>
      {band.value === '--' ? band.label : `${band.value} (${band.label})`}
    </Chip>
  )
}
