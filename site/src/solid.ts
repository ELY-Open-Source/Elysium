import {
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  CylinderGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  Shape,
  ShapeGeometry,
  Vector2,
  Vector3,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { C, tri, type Tones } from './palette';

/** Picks one of the flat tones for a face normal: top, +x face base, the diagonal mid, +y face dark. */
function toneFor(n: Vector3, t: Tones): string {
  if (n.z > 0.8) return t.top;
  if (n.z < -0.5) return t.under ?? t.dark;
  const phi = (Math.atan2(n.y, n.x) * 180) / Math.PI;
  const side = phi < 22.5 ? t.base : phi < 67.5 ? t.mid : t.dark;
  if (n.z > 0.42) return side === t.base ? t.top : t.mid;
  return side;
}

/** Colours every triangle by its own normal so curved bodies read as facets, never gradients. */
export function tone(geo: BufferGeometry, colour: string | Tones): BufferGeometry {
  const t = typeof colour === 'string' ? tri(colour) : colour;
  const flat = geo.index ? geo.toNonIndexed() : geo;
  flat.deleteAttribute('normal');
  flat.deleteAttribute('uv');
  const pos = flat.getAttribute('position');
  const colours = new Float32Array(pos.count * 3);
  const a = new Vector3();
  const b = new Vector3();
  const c = new Vector3();
  const col = new Color();
  for (let i = 0; i < pos.count; i += 3) {
    a.fromBufferAttribute(pos, i);
    b.fromBufferAttribute(pos, i + 1);
    c.fromBufferAttribute(pos, i + 2);
    const n = b.sub(a).cross(c.sub(a)).normalize();
    col.set(toneFor(n, t));
    for (let k = 0; k < 3; k++) col.toArray(colours, (i + k) * 3);
  }
  flat.setAttribute('color', new BufferAttribute(colours, 3));
  return flat;
}

/** A box by its min corner and size in metres. */
export function box(x: number, y: number, z: number, w: number, d: number, h: number): BufferGeometry {
  return new BoxGeometry(w, d, h).translate(x + w / 2, y + d / 2, z + h / 2);
}

/** An upright faceted cylinder standing on its base centre. */
export function column(x: number, y: number, z: number, r: number, h: number, sides = 10): BufferGeometry {
  return new CylinderGeometry(r, r, h, sides).rotateX(Math.PI / 2).translate(x, y, z + h / 2);
}

export function toneMaterial(): MeshBasicMaterial {
  return new MeshBasicMaterial({ vertexColors: true });
}

/** One mesh from several parts, each [geometry, colour]. */
export function solid(parts: [BufferGeometry, string | Tones][]): Mesh {
  const merged = mergeGeometries(parts.map(([g, c]) => tone(g, c)));
  if (!merged) throw new Error('solid parts do not share the same attributes');
  return new Mesh(merged, toneMaterial());
}

/** Floor layers skip the depth test and paint in order of height, so a 4 mm stack never z-fights. */
export function floorLayer(mesh: Mesh, z: number): Mesh {
  const m = mesh.material as MeshBasicMaterial;
  m.depthTest = false;
  m.depthWrite = false;
  mesh.renderOrder = Math.round(z * 1000) - 1000;
  return mesh;
}

/** Paint on the floor at height z (markings, strips, arrows), drawn before anything standing on it. */
export function paint(points: [number, number][], z: number, colour: string): Mesh {
  const shape = new Shape(points.map(([x, y]) => new Vector2(x, y)));
  const geo = new ShapeGeometry(shape).translate(0, 0, z);
  return floorLayer(new Mesh(geo, new MeshBasicMaterial({ color: colour })), z);
}

export const rect = (x0: number, x1: number, y0: number, y1: number): [number, number][] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
];

const GROUND = { value: new Color(C.ground) };

function washOf(m: MeshBasicMaterial): { value: number } {
  const known = m.userData.wash as { value: number } | undefined;
  if (known) return known;
  const wash = { value: 0 };
  m.userData.wash = wash;
  m.onBeforeCompile = (shader) => {
    shader.uniforms.uWash = wash;
    shader.uniforms.uGround = GROUND;
    shader.fragmentShader = shader.fragmentShader
      .replace('void main() {', 'uniform float uWash;\nuniform vec3 uGround;\nvoid main() {')
      .replace('#include <opaque_fragment>', '#include <opaque_fragment>\ngl_FragColor.rgb = mix(gl_FragColor.rgb, uGround, uWash);');
  };
  m.customProgramCacheKey = () => 'wash';
  m.needsUpdate = true;
  return wash;
}

/** Installs the wash on every material up front, so the first fade does not compile a shader mid-scroll. */
export function prepareWash(root: Object3D): void {
  root.traverse((o) => {
    if (o instanceof Mesh && !(o.material as MeshBasicMaterial).transparent) washOf(o.material as MeshBasicMaterial);
  });
}

/**
 * Washes every solid under a node toward the ground colour (presence 1 = as painted, 0 = gone). A wash,
 * not transparency, so a person's arm never shows through their own coat while they fade.
 */
export function fade(node: Object3D, presence: number): void {
  node.visible = presence > 0.002;
  node.traverse((o) => {
    if (o instanceof Mesh) washOf(o.material as MeshBasicMaterial).value = 1 - presence;
  });
}

/** A dashed line through floor points; reveal(p) paints the dashes in order up to fraction p. */
export function dashes(points: [number, number][], z: number, colour: string, width = 0.07): { node: Group; reveal(p: number): void } {
  const node = new Group();
  const marks: Mesh[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [ax, ay] = points[i];
    const [bx, by] = points[i + 1];
    const length = Math.hypot(bx - ax, by - ay);
    const n = Math.max(1, Math.round(length / 0.55));
    for (let k = 0; k < n; k++) {
      const f0 = k / n;
      const f1 = f0 + 0.6 / n;
      const [x0, y0] = [ax + (bx - ax) * f0, ay + (by - ay) * f0];
      const [x1, y1] = [ax + (bx - ax) * f1, ay + (by - ay) * f1];
      const along = ax === bx;
      const m = paint(
        along ? rect(x0 - width / 2, x0 + width / 2, Math.min(y0, y1), Math.max(y0, y1)) : rect(Math.min(x0, x1), Math.max(x0, x1), y0 - width / 2, y0 + width / 2),
        z,
        colour,
      );
      node.add(m);
      marks.push(m);
    }
  }
  return {
    node,
    reveal(p) {
      marks.forEach((m, i) => (m.visible = i < p * marks.length));
    },
  };
}

export interface Strip {
  mesh: Mesh;
  grow(p: number): void;
}

/** A painted strip from (x, y) along one world axis; length is signed, grow(p) paints the first p of it. */
export function strip(x: number, y: number, axis: 'x' | 'y', length: number, width: number, z: number, colour: string): Strip {
  const [a, b] = length < 0 ? [-1, 0] : [0, 1];
  const unit = axis === 'x' ? rect(a, b, -width / 2, width / 2) : rect(-width / 2, width / 2, a, b);
  const mesh = paint(unit, z, colour);
  mesh.position.set(x, y, 0);
  return {
    mesh,
    grow(p) {
      mesh.visible = p > 0.001;
      mesh.scale[axis] = Math.abs(length) * Math.max(p, 0.001);
    },
  };
}
