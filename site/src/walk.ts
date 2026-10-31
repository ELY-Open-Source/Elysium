import { clamp, seg, ss } from './ease';

/** A waypoint: be at (x, y) at time t. Two waypoints at one spot mean standing still between them. */
export type Waypoint = [t: number, x: number, y: number];

export interface Step {
  x: number;
  y: number;
  stride: number;
  phase: number;
}

const CYCLE = 1.4;

/** Samples a walk deterministically at any t, so scrolling back replays it backwards frame for frame. */
export function walkAt(path: Waypoint[], t: number): Step {
  if (path.length === 0) throw new Error('a walk needs at least one waypoint');
  let travelled = 0;
  for (let i = 0; i < path.length - 1; i++) {
    const [t0, x0, y0] = path[i];
    const [t1, x1, y1] = path[i + 1];
    if (t1 <= t0) throw new Error(`waypoint ${i + 1} is not after waypoint ${i}`);
    const length = Math.hypot(x1 - x0, y1 - y0);
    if (t < t1) {
      if (t <= t0) return { x: x0, y: y0, stride: 0, phase: (travelled / CYCLE) * Math.PI * 2 };
      const u = seg(t, t0, t1);
      const e = ss(u);
      const d = travelled + length * e;
      return {
        x: x0 + (x1 - x0) * e,
        y: y0 + (y1 - y0) * e,
        stride: length > 0 ? clamp(6 * u * (1 - u) * 1.2) : 0,
        phase: (d / CYCLE) * Math.PI * 2,
      };
    }
    travelled += length;
  }
  const [, x, y] = path[path.length - 1];
  return { x, y, stride: 0, phase: (travelled / CYCLE) * Math.PI * 2 };
}
