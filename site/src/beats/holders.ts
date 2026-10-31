import type { Group } from 'three';
import { T, X, type Beat } from '../beat';
import { actor, card, fileCard } from '../cast';
import { Chest } from '../chest';
import { FloorPhrase } from '../floortype';
import { C, LEGS, TOPS } from '../palette';
import { fade, strip } from '../solid';
import { lerp, seg, ss } from '../ease';
import { cover, fit } from '../stage';

const ROWS = [-6.6, -3.4, -0.2, 3.0];
const FILED = [16, 12, 18, 14];
const ASKER = 3;

/** Each person files memories into their own chest; a search walks only the asker's row. */
export function holders(root: Group): Beat {
  const x0 = X.holders;
  const t0 = T.holders;
  const rows = ROWS.map((yc, i) => {
    const chest = new Chest(x0 - 6, 11, yc, TOPS[i], FILED[i]);
    root.add(chest.node);
    const aisle = yc + 1.25;
    const slot = chest.slot(FILED[i]);
    const walkStart = t0 + 1.6 + i * 0.35;
    const person = actor(root, { top: TOPS[i], legs: LEGS[i], hairLong: i === 1 || i === 2 }, [
      [walkStart, x0 + 5.5, aisle],
      [walkStart + 4, slot.x + 0.15, aisle],
    ]);
    const filed = card(TOPS[i]);
    filed.visible = false;
    root.add(filed);
    return { chest, person, filed, slot, aisle, fileAt: walkStart + 4.3 };
  });

  const search = strip(x0 + 6, ROWS[ASKER] + 1.25 + 0.55, 'x', -12.5, 0.32, 0.006, C.accent);
  root.add(search.mesh);
  const phrase = new FloorPhrase({
    x: x0 + 5.2,
    y: 7.7,
    t0: t0 + 10.0,
    lines: [[['各归其主', 'B']], [['+0.455', 'na']]],
  });
  root.add(phrase.node);

  return {
    id: 'holders',
    start: t0,
    settle: t0 + 12.2,
    hover: [],
    keys: [
      [t0 + 1.6, fit(x0 - 6.5, x0 + 6.5, -7.6, 9.8, 1.8, 1.08)],
      [t0 + 11.5, fit(x0 - 6.5, x0 + 6.5, -7.6, 9.8, 1.8, 1.02)],
    ],
    portrait: [
      [t0 + 1.6, fit(...cover(phrase.box, [x0 - 2, x0 + 6.2, -0.8, 5.0]), 1.8, 1.08)],
      [t0 + 11.5, fit(...cover(phrase.box, [x0 - 1, x0 + 6.2, 2.2, 5.0]), 1.8, 1.06)],
    ],
    update(t) {
      const dim = ss(seg(t, t0 + 9.2, t0 + 10.2));
      rows.forEach((r, i) => {
        r.chest.open(t, t0 + 0.8 + i * 0.25);
        const here = r.person.at(t);
        r.person.update(t, fileCard(r.filed, here, r.slot, t, r.fileAt));
        const alpha = i === ASKER ? 1 : lerp(1, 0.28, dim);
        fade(r.chest.body, alpha);
        r.person.person.dim = alpha;
        fade(r.filed, r.filed.visible ? alpha : 0);
      });
      search.grow(ss(seg(t, t0 + 9.6, t0 + 10.8)));
      phrase.update(t);
    },
  };
}
