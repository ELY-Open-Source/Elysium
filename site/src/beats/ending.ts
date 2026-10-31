import type { Group } from 'three';
import { T, X, type Beat } from '../beat';
import { everyone } from '../cast';
import { FloorPhrase } from '../floortype';
import { fade } from '../solid';
import { seg, ss } from '../ease';
import { fit } from '../stage';

/** The place empty again, the rule left on the floor, seen whole from a step back. Runs last: it applies every person's presence. */
export function ending(root: Group): Beat {
  const t0 = T.ending;
  const phrase = new FloorPhrase({
    x: X.speed - 13,
    y: 15.5,
    t0: t0 + 3.2,
    step: 0.22,
    scale: 2.4,
    lines: [[['记住是', 'B'], ['谁', 'A'], ['的', 'B']], [['REMEMBER WHOSE IT IS', 'e']]],
  });
  root.add(phrase.node);
  return {
    id: 'ending',
    start: t0,
    settle: T.end,
    hover: [],
    keys: [
      [t0 + 4.2, fit(X.counter - 8, X.speed + 8, -7, 22, 2.9, 1.04)],
      [T.end, fit(X.counter - 8, X.speed + 8, -7, 22, 2.9, 1.0)],
    ],
    update(t) {
      const leave = ss(seg(t, t0 + 0.4, t0 + 2.0));
      for (const p of everyone) fade(p.node, p.dim * (1 - leave));
      phrase.update(t);
    },
  };
}
