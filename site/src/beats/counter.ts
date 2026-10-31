import { CanvasTexture, Color, Group, Matrix4, Mesh, MeshBasicMaterial, PlaneGeometry, SRGBColorSpace, Vector3 } from 'three';
import { T, X, type Beat } from '../beat';
import { actor } from '../cast';
import { FloorPhrase, SERIF } from '../floortype';
import { C, LEGS, TOPS } from '../palette';
import { box, solid, strip, type Strip } from '../solid';
import { seg, ss } from '../ease';
import { cover, fit } from '../stage';

const AGENTS = ['Claude Code', 'Codex', 'Cursor', 'Gemini CLI', 'OpenCode', 'VS Code'] as const;
const LANE = 1.4;
const laneY = (i: number): number => -3.5 + LANE * i;
const FACING_X = new Matrix4().makeBasis(new Vector3(0, 1, 0), new Vector3(0, 0, 1), new Vector3(1, 0, 0));

function signTexture(text: string): CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 256;
  const g = canvas.getContext('2d');
  if (!g) throw new Error('2D canvas is unavailable, the counter sign cannot be painted');
  g.font = `600 170px "${SERIF}"`;
  g.fillStyle = '#fff';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.letterSpacing = '24px';
  g.fillText(text, 512, 138);
  const tex = new CanvasTexture(canvas);
  tex.colorSpace = SRGBColorSpace;
  return tex;
}

/** Six agents walk up six lanes to one counter: one MCP server in front of one store. */
export function counter(root: Group): Beat {
  const x0 = X.counter;
  const t0 = T.counter;
  root.add(
    solid([
      [box(x0 - 5.0, -4.6, 0, 0.9, 9.2, 1.05), C.green],
      [box(x0 - 7.1, -5.2, 0, 0.35, 10.4, 2.9), C.wall],
    ]),
  );
  const panelMat = new MeshBasicMaterial({ color: C.screen });
  const panel = new Mesh(new PlaneGeometry(4.6, 1.15), panelMat);
  const letters = new Mesh(new PlaneGeometry(4.6, 1.15), new MeshBasicMaterial({ map: signTexture('MCP'), color: C.sheet, transparent: true }));
  for (const [m, dx] of [[panel, 0.01], [letters, 0.02]] as const) {
    m.applyMatrix4(FACING_X);
    m.position.set(x0 - 6.75 + dx, 0, 2.05);
    root.add(m);
  }
  const lit = { off: new Color(C.screen), on: new Color(C.accent) };

  const lanes: Strip[] = [];
  for (let k = 0; k <= AGENTS.length; k++) lanes.push(strip(x0 + 5.6, laneY(k) - LANE / 2, 'x', -9.6, 0.07, 0.006, C.ginger));
  lanes.forEach((l) => root.add(l.mesh));

  const names: FloorPhrase[] = [];
  const agents = AGENTS.map((name, i) => {
    const start = t0 + 1.8 + i * 0.45;
    const label = new FloorPhrase({ x: x0 + 6.4, y: laneY(i) + 0.3, t0: t0 + 1.0 + i * 0.12, step: 0.05, align: 'end', lines: [[[name, 'es']]] });
    names.push(label);
    root.add(label.node);
    const a = actor(root, { top: TOPS[i % 4], legs: LEGS[(i + 1) % 4], hairLong: i % 3 === 1 }, [
      [start, x0 + 5.0, laneY(i)],
      [start + 4.6, x0 - 3.5, laneY(i)],
    ]);
    return { a, name };
  });

  const phrase = new FloorPhrase({ x: x0 + 5.2, y: 6.9, t0: t0 + 8.6, lines: [[['同', 'A'], ['一个柜台', 'B']]] });
  root.add(phrase.node);

  return {
    id: 'counter',
    start: t0,
    settle: t0 + 10.4,
    hover: agents.map(({ a, name }) => ({ person: a.person, card: 'card-agent', label: name })),
    keys: [
      [t0 + 2.0, fit(x0 - 7.2, x0 + 9.8, -5.4, 7.4, 2.9, 1.06)],
      [t0 + 10, fit(x0 - 7.2, x0 + 9.8, -5.4, 7.4, 2.9, 1.02)],
    ],
    portrait: [
      [t0 + 2.0, fit(...cover(phrase.box, [x0 - 7.2, x0 + 5.6, -5.4, 4.4]), 2.9, 1.06)],
      [t0 + 10, fit(...cover(phrase.box, [x0 - 7.2, x0 + 5.6, -5.4, 4.4]), 2.9, 1.02)],
    ],
    update(t, portrait) {
      const paint = ss(seg(t, t0 + 0.4, t0 + 1.6));
      lanes.forEach((l) => l.grow(paint));
      for (const n of names) {
        n.node.visible = !portrait;
        n.update(t);
      }
      agents.forEach(({ a }) => a.update(t));
      panelMat.color.lerpColors(lit.off, lit.on, ss(seg(t, t0 + 8.3, t0 + 8.9)));
      phrase.update(t);
    },
  };
}
