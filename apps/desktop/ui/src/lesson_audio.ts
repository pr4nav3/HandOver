export interface LessonMedia {
  src: string;
  currentTime: number;
  pause(): void;
  load(): void;
  removeAttribute(name: string): void;
}

export interface SpeechStopper {
  cancel(): void;
}

/** A hard stop, unlike pause: detach the media resource so WebKit cannot keep its audio renderer alive after
 * the Learn route disappears. Dependencies are injectable so this boundary has a regression test in Node. */
export function stopLessonPlayback(media: LessonMedia, speech?: SpeechStopper) {
  speech?.cancel();
  media.pause();
  try {
    media.currentTime = 0;
  } catch {
    // A media element with no seekable range can reject the reset; detaching it still stops playback.
  }
  media.removeAttribute("src");
  media.load();
}

/** Crosses the per-step playback boundary synchronously. The outgoing source is detached before the incoming
 * source is assigned, which prevents a buffered old narration packet from surviving Next on Bluetooth. */
export function replaceLessonPlayback(media: LessonMedia, src: string, speech?: SpeechStopper) {
  stopLessonPlayback(media, speech);
  media.src = src;
  media.load();
}
