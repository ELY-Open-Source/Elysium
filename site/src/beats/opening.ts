import { Group, IcosahedronGeometry } from 'three';
import { T, X, type Beat } from '../beat';
import { actor } from '../cast';
import { FloorPhrase } from '../floortype';
import { C, LEGS, TOPS } from '../palette';
import { box, column, solid } from '../solid';
import { fit } from '../stage';

export const INTRO = 3.4;

function tree(x: number, y: number): Group {
  const g = new Group();
  g.add(
    solid([
      [box(x - 0.9, y - 0.9, 0, 1.8, 1.8, 0.45), C.carpetEdge],
      [column(x, y, 0.45, 0.12, 1.2, 6), '#7A5C44'],
      [new IcosahedronGeometry(1.15, 0).translate(x, y, 2.3), C.greenLt],
    ]),
  );
  return g;
}

/** The place empty; the title lands on the ground as the first person walks past it. */
export function opening(root: Group): Beat {
  const x0 = X.opening;
  const title = new FloorPhrase({
    x: x0 + 5.6,
    y: -1.0,
    t0: 0.5,
    step: 0.32,
    scale: 1.6,
    lines: [[['往世', 'B'], ['乐', 'A'], ['土', 'B']], [['ELYSIAN', 'e']]],
  });
  root.add(title.node);
  for (const [dx, dy] of [[-3, -9], [3.5, -9.5], [10, -9]]) root.add(tree(x0 + dx, dy));

  const walker = actor(root, { top: TOPS[0], legs: LEGS[0] }, [
    [0, x0 + 9.5, 0.1],
    [0.4, x0 + 9.5, 0.1],
    [20, x0 - 21, 0.1],
  ]);

  return {
    id: 'opening',
    start: T.opening,
    settle: INTRO,
    hover: [],
    keys: [
      [0, fit(x0 - 6, x0 + 11, -10.4, 3.4, 1.8, 1.1)],
      [7.5, fit(x0 - 6, x0 + 9, -10.2, 3.2, 1.8, 1.02)],
    ],
    update(t) {
      title.update(t);
      walker.update(t);
    },
  };
}
