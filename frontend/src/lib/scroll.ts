import Lenis from 'lenis';
import 'lenis/dist/lenis.css';
import { useEffect, useState } from 'react';

const BREATHING_ROOM = 12;

/** Smooth wheel scrolling and smooth anchor jumps that stop under the masthead, unless the viewer asked for less motion. */
export function useSmoothScroll(): void {
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return;
    }
    const masthead = document.querySelector<HTMLElement>('.masthead');
    if (!masthead) {
      throw new Error('smooth anchors need the masthead to measure, and the page has none');
    }
    const offset = -(masthead.offsetHeight + BREATHING_ROOM);
    const lenis = new Lenis({ autoRaf: true, anchors: { offset, duration: 1.1 } });
    return () => lenis.destroy();
  }, []);
}

/** The id of the section that holds the middle band of the viewport. */
export function useActiveSection(ids: string[]): string {
  const [active, setActive] = useState(ids[0]);
  const key = ids.join(' ');

  useEffect(() => {
    const watcher = new IntersectionObserver(
      (entries) => {
        const seen = entries.find((entry) => entry.isIntersecting);
        if (seen) {
          setActive(seen.target.id);
        }
      },
      { rootMargin: '-45% 0px -50% 0px' },
    );
    for (const id of key.split(' ')) {
      const node = document.getElementById(id);
      if (!node) {
        throw new Error(`the page has no section #${id} to watch`);
      }
      watcher.observe(node);
    }
    return () => watcher.disconnect();
  }, [key]);

  return active;
}
