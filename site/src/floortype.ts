import {
  CanvasTexture,
  Color,
  Group,
  LinearMipmapLinearFilter,
  Mesh,
  MeshBasicMaterial,
  PlaneGeometry,
  SRGBColorSpace,
  type Texture,
} from 'three';
import { C } from './palette';
import { eo, lerp, seg, ss } from './ease';
import type { Box } from './stage';

export const SERIF_SC = 'Noto Serif SC Sub';
export const SERIF = 'Newsreader Sub';

type Kind = 'B' | 'A' | 's' | 'n' | 'na' | 'ns' | 'nsa' | 'e' | 'en' | 'es';
interface Face {
  weight: number;
  size: number;
  colour: string;
  latin: boolean;
}
const KINDS: Record<Kind, Face> = {
  B: { weight: 700, size: 1.5, colour: C.ink, latin: false },
  A: { weight: 700, size: 1.5, colour: C.accent, latin: false },
  s: { weight: 500, size: 0.82, colour: C.ink, latin: false },
  n: { weight: 600, size: 1.5, colour: C.ink, latin: true },
  na: { weight: 600, size: 1.5, colour: C.accent, latin: true },
  ns: { weight: 500, size: 0.82, colour: C.ink, latin: true },
  nsa: { weight: 600, size: 0.82, colour: C.accent, latin: true },
  e: { weight: 600, size: 1.0, colour: C.ink, latin: true },
  en: { weight: 500, size: 0.62, colour: C.soft, latin: true },
  es: { weight: 600, size: 0.62, colour: C.ink, latin: true },
};

export type Run = [string, Kind];
export interface Phrase {
  x: number;
  y: number;
  t0: number;
  lines: Run[][];
  scale?: number;
  step?: number;
  lineStep?: number;
  indent?: number;
  align?: 'start' | 'middle' | 'end';
}

const PX = 160;
const PAD = 12;
const ASCENT = 1.0;
const DESCENT = 0.3;
const measurer = document.createElement('canvas').getContext('2d');
if (!measurer) throw new Error('2D canvas is unavailable, floor type cannot be measured');
const ctx2d = measurer;

const fontOf = (f: Face, px: number): string => `${f.weight} ${px}px "${f.latin ? SERIF : SERIF_SC}"`;

function advance(f: Face, text: string): number {
  ctx2d.font = fontOf(f, PX);
  return (ctx2d.measureText(text).width / PX) * f.size;
}

const textures = new Map<string, { tex: Texture; w: number; h: number }>();
let anisotropy = 1;
export const setAnisotropy = (a: number): void => {
  anisotropy = a;
};

function glyphTexture(f: Face, text: string): { tex: Texture; w: number; h: number } {
  const key = `${f.weight}|${f.latin}|${text}`;
  const hit = textures.get(key);
  if (hit) return hit;
  ctx2d.font = fontOf(f, PX);
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(ctx2d.measureText(text).width + PAD * 2);
  canvas.height = Math.ceil(PX * (ASCENT + DESCENT) + PAD * 2);
  const g = canvas.getContext('2d');
  if (!g) throw new Error('2D canvas is unavailable, floor type cannot be painted');
  g.font = fontOf(f, PX);
  g.fillStyle = '#fff';
  g.textBaseline = 'alphabetic';
  g.fillText(text, PAD, PAD + PX * ASCENT);
  const tex = new CanvasTexture(canvas);
  tex.colorSpace = SRGBColorSpace;
  tex.minFilter = LinearMipmapLinearFilter;
  tex.anisotropy = anisotropy;
  const made = { tex, w: canvas.width, h: canvas.height };
  textures.set(key, made);
  return made;
}

interface Glyph {
  pivot: Group;
  mat: MeshBasicMaterial;
  from: Color;
  to: Color;
  tc: number;
}

/** A phrase painted on the floor: its baseline runs toward -x (up-right on screen), glyph tops toward -y. */
export class FloorPhrase {
  readonly node = new Group();
  private readonly glyphs: Glyph[] = [];
  /** The floor rectangle the phrase covers, descenders included: [x0, x1, y0, y1]. */
  readonly box: Box = [Infinity, -Infinity, Infinity, -Infinity];

  constructor(p: Phrase) {
    const sc = p.scale ?? 1;
    const step = p.step ?? 0.14;
    let tc = p.t0;
    p.lines.forEach((line, li) => {
      const units = line.flatMap(([text, kind]) => {
        const f = { ...KINDS[kind], size: KINDS[kind].size * sc };
        return (f.latin ? [text] : [...text]).map((ch) => ({ ch, f }));
      });
      const widths = units.map(({ ch, f }) => (ch === ' ' ? 0.3 * sc : advance(f, ch)));
      const lineWidth = widths.reduce((a, w) => a + w + 0.05 * sc, -0.05 * sc);
      const lead = { start: li ? (p.indent ?? 0.55) * sc : 0, middle: -lineWidth / 2, end: -lineWidth };
      let u = lead[p.align ?? 'start'];
      const v = li * (p.lineStep ?? 1.85) * sc;
      units.forEach(({ ch, f }, i) => {
        if (ch !== ' ') {
          this.addGlyph(ch, f, p.x - u, p.y + v, tc);
          tc += step * (f.latin ? 2 : 1);
        }
        u += widths[i] + 0.05 * sc;
      });
      tc += 0.2;
    });
  }

  private addGlyph(ch: string, f: Face, x: number, y: number, tc: number): void {
    const { tex, w, h } = glyphTexture(f, ch);
    const k = f.size / PX;
    const mat = new MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false });
    const plane = new Mesh(new PlaneGeometry(w * k, h * k), mat);
    const cw = advance(f, ch);
    const top = (PAD + PX * ASCENT) * k;
    plane.position.set(-PAD * k + (w * k) / 2 - cw / 2, top - (h * k) / 2 - f.size * 0.38, 0);
    const pivot = new Group();
    pivot.position.set(cw / 2, f.size * 0.38, 0);
    pivot.add(plane);
    const anchor = new Group();
    anchor.position.set(x, y, 0.012);
    anchor.rotation.z = Math.PI;
    anchor.add(pivot);
    this.node.add(anchor);
    this.box[0] = Math.min(this.box[0], x - cw);
    this.box[1] = Math.max(this.box[1], x);
    this.box[2] = Math.min(this.box[2], y - f.size);
    this.box[3] = Math.max(this.box[3], y + f.size * 0.25);
    const ghost = f.colour === C.accent ? C.accentLt : C.ghost;
    this.glyphs.push({ pivot, mat, from: new Color(ghost), to: new Color(f.colour), tc });
  }

  /** Each character lands about 0.14 s after the last: fades in, settles from 1.22x, pale ghost to ink. */
  update(t: number): void {
    for (const g of this.glyphs) {
      const a = eo(seg(t, g.tc, g.tc + 0.3));
      g.pivot.visible = a > 0;
      if (a <= 0) continue;
      const dk = ss(seg(t, g.tc + 0.1, g.tc + 0.48));
      const sc = lerp(1.22, 1, eo(seg(t, g.tc, g.tc + 0.34)));
      g.mat.opacity = a;
      g.mat.color.lerpColors(g.from, g.to, dk);
      g.pivot.scale.setScalar(sc);
    }
  }
}
