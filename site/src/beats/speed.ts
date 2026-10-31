import { Group, InstancedMesh, Matrix4, Mesh, MeshBasicMaterial, PlaneGeometry } from 'three';
import { T, X, type Beat } from '../beat';
import { actor } from '../cast';
import { FloorPhrase } from '../floortype';
import { C, LEGS, TOPS, tri } from '../palette';
import { box, fade, paint, rect, solid, strip, tone, toneMaterial } from '../solid';
import { lerp, seg, ss } from '../ease';
import { fit } from '../stage';

const W0 = -7;
const W1 = 5;
const D0 = -6;
const D1 = 3;
const WALL_H = 2.6;
const PARAPET = 0.5;
const DOOR_Y = -1.3;
const AISLE_X = -3;
const PITCH = 0.5;

function building(x0: number): Mesh {
  const t = 0.18;
  return solid([
    [box(x0 + W0, D0, 0, t, D1 - D0, WALL_H), C.wall],
    [box(x0 + W0, D0, 0, W1 - W0, t, WALL_H), C.wall],
    [box(x0 + W1 - t, D0, 0, t, DOOR_Y - 0.8 - D0, PARAPET), C.wall],
    [box(x0 + W1 - t, DOOR_Y + 0.8, 0, t, D1 - DOOR_Y - 0.8, PARAPET), C.wall],
    [box(x0 + W0, D1 - t, 0, W1 - W0, t, PARAPET), C.wall],
  ]);
}

function windows(x0: number, root: Group): void {
  for (let i = 0; i < 5; i++) {
    const glass = new Mesh(new PlaneGeometry(1.3, 1.1), new MeshBasicMaterial({ color: C.glass }));
    glass.rotation.set(-Math.PI / 2, 0, 0);
    glass.position.set(x0 + W0 + 1.85 + i * 2.2, D0 + 0.19, 1.55);
    root.add(glass);
  }
}

/** One SQLite file holds every memory; the lid lifts, the cards weave in, and a search lands at once. */
export function speed(root: Group): Beat {
  const x0 = X.speed;
  const t0 = T.speed;
  root.add(paint(rect(x0 + W0, x0 + W1, D0, D1), 0.004, C.carpet));
  root.add(building(x0));
  windows(x0, root);

  const tiles: { x: number; y: number; order: number; colour: number }[] = [];
  for (let i = 0; i * PITCH < W1 - W0 - 1.4; i++) {
    for (let j = 0; j * PITCH < D1 - D0 - 1.2; j++) {
      const x = x0 + W1 - 0.9 - i * PITCH;
      const y = D1 - 0.6 - j * PITCH;
      if (Math.abs(y - DOOR_Y) < 0.45 || Math.abs(x - (x0 + AISLE_X)) < 0.45) continue;
      tiles.push({ x, y, order: i + j, colour: (i + 2 * j) % 4 });
    }
  }
  const target = tiles.reduce((a, b) => (Math.hypot(b.x - (x0 + AISLE_X - 0.5), b.y + 4.3) < Math.hypot(a.x - (x0 + AISLE_X - 0.5), a.y + 4.3) ? b : a));
  const lastOrder = Math.max(...tiles.map((t) => t.order));
  const sets = TOPS.map((top, c) => {
    const mine = tiles.filter((t) => t.colour === c);
    const mesh = new InstancedMesh(tone(box(-0.18, -0.18, 0, 0.36, 0.36, 0.3), tri(top, 0.3, 0.2)), toneMaterial(), mine.length);
    root.add(mesh);
    return { mesh, mine };
  });
  const found = solid([[box(-0.18, -0.18, 0, 0.36, 0.36, 0.3), C.accent]]);
  root.add(found);

  const roof = new Group();
  roof.position.set(x0 + (W0 + W1) / 2, D0, WALL_H);
  roof.add(solid([[box(-(W1 - W0) / 2 - 0.2, -0.2, 0, W1 - W0 + 0.4, D1 - D0 + 0.4, 0.2), { ...tri(C.green), under: C.sheet }]]));
  root.add(roof);

  const asker = actor(root, { top: TOPS[3], legs: LEGS[3] }, [
    [t0 + 1.4, x0 + 10.5, DOOR_Y],
    [t0 + 4.6, x0 + 6.0, DOOR_Y],
  ]);
  const runIn = strip(x0 + W1 + 0.6, DOOR_Y, 'x', AISLE_X - W1 - 0.6, 0.2, 0.008, C.accent);
  const runUp = strip(x0 + AISLE_X, DOOR_Y, 'y', target.y - DOOR_Y, 0.2, 0.008, C.accent);
  root.add(runIn.mesh, runUp.mesh);

  const phrase = new FloorPhrase({
    x: x0 + 4.6,
    y: 6.6,
    t0: t0 + 7.0,
    lines: [[['0.072', 'na'], [' 秒', 's']], [['165,973', 'ns'], [' 条记忆，一个文件', 's']]],
  });
  root.add(phrase.node);
  const m = new Matrix4();

  return {
    id: 'speed',
    start: t0,
    settle: t0 + 10.2,
    hover: [],
    keys: [
      [t0 + 2.0, fit(x0 - 7.5, x0 + 11, -6.5, 8.6, 2.6, 1.0)],
      [t0 + 4.8, fit(x0 - 7.5, x0 + 7, -6.5, 8.6, 2.6, 1.04)],
    ],
    update(t) {
      const turn = ss(seg(t, t0 + 2.2, t0 + 3.6));
      const glide = ss(seg(t, t0 + 3.4, t0 + 4.4));
      roof.rotation.x = turn * (Math.PI - 0.04);
      roof.position.y = D0 - glide * 3;
      fade(roof, 1 - glide);
      const fill = seg(t, t0 + 3.6, t0 + 6.0);
      const ask = t0 + 6.2;
      const lift = ss(seg(t, ask + 0.55, ask + 1.0));
      for (const { mesh, mine } of sets) {
        mine.forEach((tile, k) => {
          const grown = ss(seg(fill * (lastOrder + 6), tile.order, tile.order + 6));
          const s = tile === target && lift > 0 ? 0 : grown;
          const k3 = Math.max(s, 0.001);
          m.makeScale(k3, k3, k3).setPosition(tile.x, tile.y, 0.004);
          mesh.setMatrixAt(k, m);
        });
        mesh.instanceMatrix.needsUpdate = true;
      }
      runIn.grow(ss(seg(t, ask, ask + 0.35)));
      runUp.grow(ss(seg(t, ask + 0.3, ask + 0.6)));
      found.visible = lift > 0;
      found.position.set(target.x, target.y, lerp(0.004, 0.45, lift));
      asker.update(t);
      phrase.update(t);
    },
  };
}
