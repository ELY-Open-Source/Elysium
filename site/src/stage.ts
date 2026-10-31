import { Color, OrthographicCamera, Scene, SRGBColorSpace, Vector3, WebGLRenderer } from 'three';
import { C } from './palette';
import { eio, lerp, seg } from './ease';

/** What the camera looks at: a floor point and the half-extent, in camera units, that must stay in view. */
export interface Frame {
  x: number;
  y: number;
  hw: number;
  hh: number;
}
export type Key = [t: number, frame: Frame];
/** A floor rectangle: [x0, x1, y0, y1] in metres. */
export type Box = [number, number, number, number];

/** The smallest floor rectangle holding every given one. */
export function cover(...boxes: Box[]): Box {
  return [
    Math.min(...boxes.map((b) => b[0])),
    Math.max(...boxes.map((b) => b[1])),
    Math.min(...boxes.map((b) => b[2])),
    Math.max(...boxes.map((b) => b[3])),
  ];
}

const VIEW = new Vector3(1, 1, 1).normalize();
const MAX_PIXELS = 5_000_000;

/**
 * The frame that holds a floor box, and anything standing up to `top` metres on it, with a margin.
 * In camera units a floor point lands at u = (y - x) / sqrt 2 across and v = (x + y - 2z) / sqrt 6 down.
 */
export function fit(x0: number, x1: number, y0: number, y1: number, top = 1.8, margin = 1.05): Frame {
  const us: number[] = [];
  const vs: number[] = [];
  for (const x of [x0, x1]) {
    for (const y of [y0, y1]) {
      for (const z of [0, top]) {
        us.push((y - x) / Math.SQRT2);
        vs.push((x + y - 2 * z) / Math.sqrt(6));
      }
    }
  }
  const [u0, u1, v0, v1] = [Math.min(...us), Math.max(...us), Math.min(...vs), Math.max(...vs)];
  const uc = (u0 + u1) / 2;
  const vc = (v0 + v1) / 2;
  return {
    x: (vc * Math.sqrt(6) - uc * Math.SQRT2) / 2,
    y: (vc * Math.sqrt(6) + uc * Math.SQRT2) / 2,
    hw: ((u1 - u0) / 2) * margin,
    hh: ((v1 - v0) / 2) * margin,
  };
}

/** Like fit, but the band's height sets the zoom and the sides are cropped: a portrait screen filled by a subject wider than tall. */
export function fill(x0: number, x1: number, y0: number, y1: number, top = 1.8, margin = 1.05): Frame {
  return { ...fit(x0, x1, y0, y1, top, margin), hw: 1e-3 };
}

/** Each beat's camera holds its last frame until the next beat's travel begins. */
export function holdKeys(beats: { start: number; keys: Key[]; portrait: Key[] }[], portrait: boolean): Key[] {
  const held = beats.flatMap((b, i) => {
    const keys = portrait ? b.portrait : b.keys;
    const next = beats[i + 1];
    const last = keys[keys.length - 1];
    const hold = next ? next.start - 1.4 : -Infinity;
    return hold > last[0] ? [...keys, [hold, last[1]] as Key] : keys;
  });
  held.forEach(([t], i) => {
    if (i > 0 && t <= held[i - 1][0]) throw new Error(`camera key at t=${t} follows one at t=${held[i - 1][0]}; frameAt would jump`);
  });
  return held;
}

/** Interpolates camera keys: translation eases, zoom eases in log space so a pull-out feels even. */
export function frameAt(keys: Key[], t: number): Frame {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 0; i < keys.length - 1; i++) {
    const [t0, a] = keys[i];
    const [t1, b] = keys[i + 1];
    if (t <= t1) {
      const e = eio(seg(t, t0, t1));
      return {
        x: lerp(a.x, b.x, e),
        y: lerp(a.y, b.y, e),
        hw: Math.exp(lerp(Math.log(a.hw), Math.log(b.hw), e)),
        hh: Math.exp(lerp(Math.log(a.hh), Math.log(b.hh), e)),
      };
    }
  }
  return keys[keys.length - 1][1];
}

export class Stage {
  readonly scene = new Scene();
  readonly camera = new OrthographicCamera(-1, 1, 1, -1, 1, 1600);
  readonly renderer: WebGLRenderer;
  private width = 1;
  private height = 1;

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.setClearColor(new Color(C.ground));
    this.scene.background = new Color(C.ground);
    this.camera.up.set(0, 0, 1);
  }

  get anisotropy(): number {
    return this.renderer.capabilities.getMaxAnisotropy();
  }

  resize(width: number, height: number): void {
    this.width = width;
    this.height = height;
    const ratio = Math.min(window.devicePixelRatio, 2);
    this.renderer.setPixelRatio(Math.min(ratio, Math.sqrt(MAX_PIXELS / (width * height))));
    this.renderer.setSize(width, height, false);
  }

  /**
   * Frames the floor box in the band above the caption; the angle never changes, only translation and
   * zoom. On a tall band the width sets the zoom, and `settleLow` rests the box on the caption so the
   * spare height above shows more of the place instead of empty ground below.
   */
  look(f: Frame, reserveBottom: number, settleLow: boolean): void {
    const band = Math.max(this.height - reserveBottom, this.height * 0.4);
    const k = Math.min(this.width / (2 * f.hw), band / (2 * f.hh));
    const cy = settleLow ? band - f.hh * k : band / 2;
    const target = new Vector3(f.x, f.y, 0);
    this.camera.position.copy(target).addScaledVector(VIEW, 600);
    this.camera.lookAt(target);
    this.camera.left = -this.width / 2 / k;
    this.camera.right = this.width / 2 / k;
    this.camera.top = cy / k;
    this.camera.bottom = -(this.height - cy) / k;
    this.camera.updateProjectionMatrix();
  }

  render(): void {
    this.renderer.render(this.scene, this.camera);
  }
}
