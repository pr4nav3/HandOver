// Line icons, drawn at 24 units like the web app's. Markup only; color comes from currentColor.

import { raw } from "./util";

const svg = (size: number, body: string, stroke = 1.8) =>
  raw(
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`,
  );

const cameraBody =
  '<path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.3l1.4-2h7.6l1.4 2h1.3A2.5 2.5 0 0 1 21 8.5v9a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/><circle cx="12" cy="13" r="3.6"/>';

export const icons = {
  mark: raw(
    '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6.6 10.6 3.4 3.2 7.2-7.2" stroke="currentColor" stroke-width="2.2"/><path d="M6.5 18.5h2.6M10.7 18.5h2.6" stroke="var(--green)" stroke-width="2"/><path d="M14.9 18.5h2.6" stroke="currentColor" stroke-opacity="0.35" stroke-width="2"/></svg>',
  ),
  hub: svg(16, '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'),
  close: svg(14, '<path d="M6 6l12 12M18 6 6 18"/>', 2),
  gear: svg(
    17,
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    1.6,
  ),
  back: svg(16, '<path d="M15 18l-6-6 6-6"/>', 2),
  camera: svg(40, cameraBody, 1.4),
  smallCamera: svg(14, cameraBody),
  hand: svg(
    14,
    '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12m0-1.5v-6a1.5 1.5 0 0 1 3 0V12m0-5.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-.5a6 6 0 0 1-4.9-2.5L3.3 15a1.5 1.5 0 0 1 2.4-1.8L8 15.5"/>',
  ),
  check: svg(36, '<circle cx="12" cy="12" r="9.5"/><path d="m7.8 12.3 2.8 2.8 5.6-5.8"/>', 1.6),
  sound: svg(15, '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>'),
  chevron: svg(16, '<path d="m9 6 6 6-6 6"/>', 2),
  refresh: svg(15, '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>'),
  film: svg(28, '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>', 1.4),
  filmBig: svg(40, '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>', 1.3),
  star: svg(16, '<path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>', 1.6),
  starFill: raw('<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>'),
  home: svg(18, '<path d="M4 10.5 12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5H15v-6H9v6H5.5A1.5 1.5 0 0 1 4 19z"/>', 1.7),
  grid: svg(18, '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>', 1.7),
  people: svg(18, '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><circle cx="17" cy="9.5" r="2.5"/><path d="M15.5 14.2A4.5 4.5 0 0 1 21 18.5"/>', 1.7),
  peopleBig: svg(40, '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><circle cx="17" cy="9.5" r="2.5"/><path d="M15.5 14.2A4.5 4.5 0 0 1 21 18.5"/>', 1.3),
  teach: svg(18, '<rect x="3" y="6" width="13" height="12" rx="2.5"/><path d="m16 10.5 5-3v9l-5-3"/><path d="M9.5 9.5v5M7 12h5"/>', 1.7),
  teachBig: svg(24, '<rect x="3" y="6" width="13" height="12" rx="2.5"/><path d="m16 10.5 5-3v9l-5-3"/><path d="M9.5 9.5v5M7 12h5"/>', 1.6),
  person: svg(18, '<circle cx="12" cy="8.5" r="3.6"/><path d="M5 20a7 7 0 0 1 14 0"/>', 1.7),
  search: svg(15, '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>', 1.9),
  plus: svg(15, '<path d="M12 5v14M5 12h14"/>', 2),
  folder: svg(24, '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.6l2 2.2h7.4A2.5 2.5 0 0 1 21 9.7v7.8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>', 1.6),
  record: svg(24, '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.6" fill="currentColor"/>', 1.6),
  scissors: svg(15, '<circle cx="6" cy="7" r="2.6"/><circle cx="6" cy="17" r="2.6"/><path d="M8.2 8.4 20 17M8.2 15.6 20 7"/>', 1.8),
  merge: svg(15, '<path d="M6 4v5a5 5 0 0 0 5 5h7M6 20v-2M18 10l3 4-3 4"/>', 1.8),
  trash: svg(15, '<path d="M4.5 7h15M10 4h4M6.5 7l1 12.5h9l1-12.5"/>', 1.8),
  undo: svg(16, '<path d="M9 7 4.5 11.5 9 16"/><path d="M5 11.5h9a5.5 5.5 0 0 1 0 11h-2" transform="translate(0 -4)"/>', 1.8),
  redo: svg(16, '<path d="m15 7 4.5 4.5L15 16"/><path d="M19 11.5h-9a5.5 5.5 0 0 0 0 11h2" transform="translate(0 -4)"/>', 1.8),
  play: raw('<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m10 8.3 6 3.7-6 3.7z" fill="var(--panel)"/></svg>'),
  checkFill: raw('<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m7.8 12.3 2.8 2.8 5.6-5.8" fill="none" stroke="var(--panel)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'),
  tap: svg(18, '<path d="M9.5 12V5.8a1.6 1.6 0 0 1 3.2 0V11l4.6.9a2 2 0 0 1 1.6 2.3l-.8 4.3A2.5 2.5 0 0 1 15.6 20.5h-3.7a3 3 0 0 1-2.3-1.1l-3.4-4.2a1.5 1.5 0 0 1 2.2-2z"/>', 1.6),
  skipped: svg(18, '<circle cx="12" cy="12" r="9.5"/><path d="M8 13.5a4 4 0 0 1 7.5-2M15.5 8.5v3h-3"/>', 1.6),
  ring0: svg(18, '<circle cx="12" cy="12" r="9.5"/>', 1.5),
  bulb: svg(20, '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z"/>', 1.6),
  shield: svg(16, '<path d="M12 3.5 5 6v5.5c0 4.3 3 7.6 7 9 4-1.4 7-4.7 7-9V6z"/><path d="M12 8.5v4M12 15.5v.1"/>', 1.8),
  link: svg(15, '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>', 1.8),
  key: svg(16, '<circle cx="8" cy="15" r="4"/><path d="m11 12 8.5-8.5M16 7l2.5 2.5M14 9l2 2"/>', 1.8),
  grad: svg(24, '<path d="M2.5 9 12 4.5 21.5 9 12 13.5z"/><path d="M6.5 11v4.5c1.6 1.6 3.4 2.3 5.5 2.3s3.9-.7 5.5-2.3V11M21.5 9v5"/>', 1.6),
  eye: svg(16, '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>', 1.7),
  wave: svg(22, '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 10.5v3"/>', 1.8),
  viewfinder: svg(40, '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><circle cx="12" cy="12" r="3"/>', 1.4),
};
