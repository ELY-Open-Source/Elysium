import type { Group } from 'three';
import { T, X, type Beat } from '../beat';
import { actor } from '../cast';
import { Chest } from '../chest';
import { FloorPhrase } from '../floortype';
import { C, LEGS, TOPS } from '../palette';
import { paint, strip } from '../solid';
import { seg, ss } from '../ease';
import { fit } from '../stage';

const HUSBAND = 1;
const WIFE = 2;

/** His chest is empty; instead of inventing an answer, an arrow grows to the one who knows. */
export function referral(root: Group): Beat {
  const x0 = X.referral;
  const t0 = T.referral;
  const his = new Chest(x0 + 2, 5, 0, null, 0);
  const hers = new Chest(x0 - 7, 5, 0, TOPS[WIFE], 1);
  root.add(his.node, hers.node);

  const husband = actor(root, { top: TOPS[HUSBAND], legs: LEGS[HUSBAND] }, [
    [t0 + 1.2, x0 + 11, 1.3],
    [t0 + 4.4, x0 + 4.4, 1.3],
  ]);
  const wife = actor(root, { top: TOPS[WIFE], legs: LEGS[WIFE], hairLong: true }, [[0, x0 - 4.6, 1.3]]);

  const arrowY = 2.35;
  const shaft = strip(x0 + 3.4, arrowY, 'x', -6.2, 0.22, 0.006, C.accent);
  const head = paint([[0, -0.45], [0, 0.45], [-0.75, 0]], 0.006, C.accent);
  root.add(shaft.mesh, head);

  const phrase = new FloorPhrase({
    x: x0 + 2.4,
    y: 5.2,
    t0: t0 + 7.4,
    lines: [[['她', 'A'], ['知道', 'B']]],
  });
  root.add(phrase.node);

  return {
    id: 'referral',
    start: t0,
    settle: t0 + 9.6,
    hover: [
      { person: husband.person, card: 'card-husband' },
      { person: wife.person, card: 'card-wife' },
    ],
    keys: [
      [t0 + 1.8, fit(x0 - 7.5, x0 + 7.5, -1.2, 5.6, 1.8, 1.12)],
      [t0 + 9.5, fit(x0 - 7.5, x0 + 7.5, -1.2, 5.6, 1.8, 1.04)],
    ],
    update(t) {
      his.open(t, t0 + 4.6);
      hers.open(t, t0 + 5.6);
      husband.update(t);
      wife.update(t);
      const p = ss(seg(t, t0 + 6.6, t0 + 7.8));
      shaft.grow(p);
      head.visible = p > 0.02;
      head.position.set(x0 + 3.4 - 6.2 * p, arrowY, 0);
      phrase.update(t);
    },
  };
}
