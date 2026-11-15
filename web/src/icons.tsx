// Line icons on a 24 unit grid, ported from the desktop app (apps/desktop/ui/src/icons.ts).
// Markup only: color comes from currentColor, so a parent's `color` tints them.
// Strokes are capped at 1.5 so the line weight matches the hairlines on cream paper.
// The bodies are fixed strings in this file, never user input.

type IconProps = { size?: number; className?: string; title?: string }

const MAX_STROKE = 1.5

function line(defaultSize: number, body: string, stroke = 1.8) {
  return function Icon({ size = defaultSize, className, title }: IconProps) {
    return (
      <svg
        className={className}
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={Math.min(stroke, MAX_STROKE)}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden={title ? undefined : true}
        role={title ? 'img' : undefined}
        aria-label={title}
        dangerouslySetInnerHTML={{ __html: body }}
      />
    )
  }
}

const cameraBody =
  '<path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.3l1.4-2h7.6l1.4 2h1.3A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/><circle cx="12" cy="13" r="3.6"/>'
const filmBody = '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>'
const teachBody = '<rect x="3" y="6" width="13" height="12" rx="2.5"/><path d="m16 10.5 5-3v9l-5-3"/><path d="M9.5 9.5v5M7 12h5"/>'

/** The HandOver mark: a check over a three part progress bar. */
export function MarkIcon({ size = 22, className }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m6.6 10.6 3.4 3.2 7.2-7.2" stroke="currentColor" strokeWidth="2.2" />
      <path d="M6.5 18.5h2.6M10.7 18.5h2.6" stroke="var(--green)" strokeWidth="2" />
      <path d="M14.9 18.5h2.6" stroke="currentColor" strokeOpacity="0.35" strokeWidth="2" />
    </svg>
  )
}

/** Learn: a mortarboard. */
export const GradIcon = line(24, '<path d="M2.5 9 12 4.5 21.5 9 12 13.5z"/><path d="M6.5 11v4.5c1.6 1.6 3.4 2.3 5.5 2.3s3.9-.7 5.5-2.3V11M21.5 9v5"/>', 1.6)
/** Teach: a video camera with a plus. */
export const TeachIcon = line(18, teachBody, 1.7)
export const TeachBigIcon = line(24, teachBody, 1.6)
export const VideoIcon = TeachBigIcon
/** Community: a grid of tiles. */
export const GridIcon = line(
  18,
  '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  1.7,
)
export const CommunityIcon = GridIcon
export const SearchIcon = line(15, '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>', 1.9)
export const CloseIcon = line(14, '<path d="M6 6l12 12M18 6 6 18"/>', 2)
/** Hand with a finger down: a manual step. */
export const TapIcon = line(
  18,
  '<path d="M9.5 12V5.8a1.6 1.6 0 0 1 3.2 0V11l4.6.9a2 2 0 0 1 1.6 2.3l-.8 4.3A2.5 2.5 0 0 1 15.6 20.5h-3.7a3 3 0 0 1-2.3-1.1l-3.4-4.2a1.5 1.5 0 0 1 2.2-2z"/>',
  1.6,
)
export const SkippedIcon = line(18, '<circle cx="12" cy="12" r="9.5"/><path d="M8 13.5a4 4 0 0 1 7.5-2M15.5 8.5v3h-3"/>', 1.6)
/** An empty ring: a step not done yet. */
export const Ring0Icon = line(18, '<circle cx="12" cy="12" r="9.5"/>', 1.5)
export const ChevronLeftIcon = line(16, '<path d="M15 18l-6-6 6-6"/>', 2)
export const ChevronRightIcon = line(16, '<path d="m9 6 6 6-6 6"/>', 2)
export const FilmIcon = line(28, filmBody, 1.4)
export const CameraIcon = line(40, cameraBody, 1.4)
export const PhoneIcon = line(22, '<rect x="7" y="2.8" width="10" height="18.4" rx="2.4"/><path d="M10.8 18h2.4"/>', 1.6)
export const QrIcon = line(
  17,
  '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2.5v2.5H14zM17.5 17.5H20V20h-2.5zM14 19.5V20M20 14v.5"/>',
  1.7,
)
export const SoundIcon = line(15, '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>')
/** Caution triangle, as the Learn mistake card draws it. */
export const WarningIcon = line(20, '<path d="M10.3 4.2a2 2 0 0 1 3.4 0l7.6 13A2 2 0 0 1 19.6 20H4.4a2 2 0 0 1-1.7-2.8z"/><path d="M12 9.5v4M12 16.8v.2"/>', 1.9)

/** A filled circle with a check cut out: verified, done. */
export function CheckFillIcon({ size = 18, className }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="currentColor" />
      <path d="m7.8 12.3 2.8 2.8 5.6-5.8" fill="none" stroke="var(--panel)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** A filled circle with a play triangle cut out. */
export function PlayIcon({ size = 18, className }: IconProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="currentColor" />
      <path d="m10 8.3 6 3.7-6 3.7z" fill="var(--panel)" />
    </svg>
  )
}
