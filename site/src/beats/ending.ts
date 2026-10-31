import type { Group } from 'three';
import { T, X, type Beat } from '../beat';
import { everyone } from '../cast';
import { FloorPhrase, type Run } from '../floortype';
import { fade } from '../solid';
import { seg, ss } from '../ease';
import { fit } from '../stage';

/**
 * The place empty again, the rule left on the floor: seen whole from a step back on a wide screen, the
 * rule alone on a portrait one. Runs last: it applies every person's presence.
 */
export function ending(root: Group): Beat {
  const t0 = T.ending;
  const rule: Run[] = [['记住是', 'B'], ['谁', 'A'], ['的', 'B']];
  const phrase = new FloorPhrase({ x: X.speed - 13, y: 21, t0: t0 + 3.2, step: 0.22, scale: 2.4, lines: [rule] });
  const english = new FloorPhrase({ x: X.speed - 14.3, y: 21 + 1.85 * 2.4, t0: t0 + 4.6, scale: 2.4, lines: [[['REMEMBER WHOSE IT IS', 'e']]] });
  // On a portrait screen the rule lands past the counter, where nothing stands above it in the column.
  const tall = new FloorPhrase({ x: X.counter - 16, y: 12, t0: t0 + 3.2, step: 0.22, scale: 2.4, lines: [rule] });
  root.add(phrase.node, english.node, tall.node);
  return {
    id: 'ending',
    start: t0,
    settle: T.end,
    hover: [],
    keys: [
      [t0 + 4.2, fit(X.counter - 8, X.speed + 8, -7, 27, 2.9, 1.04)],
      [T.end, fit(X.counter - 8, X.speed + 8, -7, 27, 2.9, 1.0)],
    ],
    portrait: [
      [t0 + 4.2, fit(...tall.box, 0, 1.45)],
      [T.end, fit(...tall.box, 0, 1.35)],
    ],
    update(t, portrait) {
      const leave = ss(seg(t, t0 + 0.4, t0 + 2.0));
      for (const p of everyone) fade(p.node, p.dim * (1 - leave));
      for (const p of [phrase, english, tall]) {
        p.node.visible = (p === tall) === portrait;
        p.update(t);
      }
    },
  };
}
