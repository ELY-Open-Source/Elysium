import Lenis from 'lenis';
import { clamp } from './ease';
import type { Beat } from './beat';

export interface Clock {
  /** Film time for the current scroll position. */
  time(): number;
  /** Scrolls so the given film time is on screen. */
  seek(t: number): void;
}

function sectionOf(id: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-beat="${id}"]`);
  if (!el) throw new Error(`no section in index.html for beat "${id}"`);
  return el;
}

/** The beat whose caption is showing at film time t: the last one that has started. */
export function beatAt(beats: Beat[], t: number): Beat {
  let current = beats[0];
  for (const b of beats) if (t >= b.start) current = b;
  return current;
}

/**
 * Lays the sections out so scroll length follows film time, then maps scroll to time:
 * scrolling back rewinds, because every frame is a function of that time alone.
 */
export function scrollClock(beats: Beat[], from: number, to: number, smooth: boolean, onScroll: () => void): Clock {
  beats.forEach((b, i) => {
    const next = i + 1 < beats.length ? beats[i + 1].start : to;
    const section = sectionOf(b.id);
    section.style.setProperty('--len', String(next - Math.max(b.start, from)));
    section.dataset.settle = String(clamp((b.settle - from) / (to - from)));
    section.dataset.start = String(clamp((b.start - from) / (to - from)));
  });
  const limit = (): number => document.documentElement.scrollHeight - window.innerHeight;
  const lenis = smooth ? new Lenis({ autoRaf: true, lerp: 0.085 }) : null;
  if (lenis) lenis.on('scroll', onScroll);
  else window.addEventListener('scroll', onScroll, { passive: true });
  return {
    time() {
      const y = lenis ? lenis.scroll : window.scrollY;
      return from + clamp(y / limit()) * (to - from);
    },
    seek(t) {
      const y = clamp((t - from) / (to - from)) * limit();
      if (lenis) lenis.scrollTo(y, { duration: 1.2 });
      else window.scrollTo(0, y);
    },
  };
}

/** Shows one caption at a time, switched hard; focusing a hidden caption's link scrolls to its beat. */
export function captions(beats: Beat[], clock: Clock): (t: number) => Beat {
  const cues = new Map(beats.map((b) => [b.id, sectionOf(b.id).querySelector<HTMLElement>('.cue')]));
  let shown: string | null = null;
  for (const b of beats) {
    const cue = cues.get(b.id);
    if (!cue) throw new Error(`section "${b.id}" has no .cue`);
    cue.addEventListener('focusin', () => {
      if (shown !== b.id) clock.seek(b.settle);
    });
  }
  return (t) => {
    const beat = beatAt(beats, t);
    if (beat.id !== shown) {
      cues.forEach((cue, id) => cue?.classList.toggle('on', id === beat.id));
      shown = beat.id;
    }
    return beat;
  };
}
