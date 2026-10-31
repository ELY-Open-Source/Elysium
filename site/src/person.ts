import {
  BufferAttribute,
  BufferGeometry,
  CircleGeometry,
  Group,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
  Shape,
  ShapeGeometry,
  Vector3,
} from 'three';
import { C, mix, tri } from './palette';

export interface Look {
  top: string;
  legs: string;
  h?: number;
  hairLong?: boolean;
}

/** stride 0..1 scales the leg scissor and the bob, so a walker settles instead of snapping still. */
export interface Pose {
  stride: number;
  phase: number;
  lift: number;
}

// True isometric shrinks floor and height by sqrt(2/3) but not screen-width, so the cut-out narrows to match.
const ISO = Math.sqrt(2 / 3);
const FACING = new Matrix4().makeBasis(
  new Vector3(-1, 1, 0).normalize(),
  new Vector3(0, 0, 1),
  new Vector3(1, 1, 0).normalize(),
);

function flat(geo: BufferGeometry, colour: string, layer: number): Mesh {
  const m = new Mesh(geo, new MeshBasicMaterial({ color: colour }));
  m.position.z = layer * 0.002;
  return m;
}

function outline(points: [number, number][], h: number): Shape {
  const s = new Shape();
  points.forEach(([x, y], i) => (i ? s.lineTo(x * h, y * h) : s.moveTo(x * h, y * h)));
  return s;
}

function torso(h: number, from: number): Shape {
  const s = new Shape();
  s.moveTo(from * h, 0.5 * h);
  if (from < 0) {
    s.lineTo(-0.12 * h, 0.78 * h);
    s.quadraticCurveTo(-0.12 * h, 0.81 * h, -0.09 * h, 0.815 * h);
  } else {
    s.lineTo(from * h, 0.815 * h);
  }
  s.lineTo(0.09 * h, 0.815 * h);
  s.quadraticCurveTo(0.12 * h, 0.81 * h, 0.12 * h, 0.78 * h);
  s.lineTo(0.105 * h, 0.5 * h);
  return s;
}

function ellipse(rx: number, ry: number, x: number, y: number): BufferGeometry {
  return new CircleGeometry(1, 18).scale(rx, ry, 1).translate(x, y, 0);
}

/** A small faceless figure seen from behind, standing in the plane that faces the camera. */
export class Person {
  readonly node = new Group();
  readonly hit: Mesh;
  /** How present a beat wants this person (1 = fully); the ending multiplies it out. */
  dim = 1;
  private readonly body = new Group();
  private readonly legs: { geo: BufferGeometry; shoe: Mesh; hx: number; side: number }[] = [];
  private readonly arms: { pivot: Object3D; side: number }[] = [];
  private readonly h: number;

  constructor(look: Look) {
    const h = look.h ?? 1.72;
    this.h = h;
    const torsoTone = tri(look.top, 0.18, 0.26);
    const legDark = mix(look.legs, '#15171A', 0.25);
    const inner = new Group();
    inner.applyMatrix4(FACING);
    inner.scale.x = ISO;
    this.node.add(inner);
    inner.add(this.body);

    this.addLeg(0.04, 1, legDark, 0);
    this.addLeg(-0.04, -1, look.legs, 2);
    this.addArm(0.125, 1, torsoTone.dark, 4);
    this.body.add(flat(new ShapeGeometry(torso(h, -0.105)), torsoTone.base, 5));
    this.body.add(flat(new ShapeGeometry(torso(h, 0.03)), torsoTone.dark, 6));
    this.addArm(-0.125, -1, torsoTone.base, 7);
    this.body.add(flat(new PlaneGeometry(0.044 * h, 0.06 * h).translate(0, 0.82 * h, 0), mix(C.skin, '#5A3A2A', 0.15), 8));
    if (look.hairLong) {
      const hair = outline([[-0.07, 0.73], [0.07, 0.73], [0.07, 0.9], [-0.07, 0.9]], h);
      this.body.add(flat(new ShapeGeometry(hair), C.hair, 9));
    }
    this.body.add(flat(new CircleGeometry(0.066 * h, 24).translate(0, 0.885 * h, 0), C.hair, 10));
    this.body.add(flat(ellipse(0.012 * h, 0.02 * h, -0.058 * h, 0.872 * h), C.skin, 11));

    this.hit = new Mesh(new PlaneGeometry(0.34 * h, h).translate(0, h / 2, 0), new MeshBasicMaterial());
    this.hit.visible = false;
    inner.add(this.hit);
    this.pose({ stride: 0, phase: 0, lift: 0 });
  }

  private addLeg(hx: number, side: number, colour: string, layer: number): void {
    const geo = new BufferGeometry();
    geo.setAttribute('position', new BufferAttribute(new Float32Array(12), 3));
    geo.setIndex([0, 1, 2, 0, 2, 3]);
    this.body.add(flat(geo, colour, layer));
    const shoe = flat(ellipse(0.04 * this.h, 0.016 * this.h, 0, 0), C.shoe, layer + 1);
    this.body.add(shoe);
    this.legs.push({ geo, shoe, hx, side });
  }

  private addArm(x: number, side: number, colour: string, layer: number): void {
    const h = this.h;
    const pivot = new Object3D();
    pivot.position.set(x * h, 0.79 * h, layer * 0.002);
    const sleeve = new Shape();
    sleeve.moveTo(-0.026 * h, 0);
    sleeve.lineTo(0.026 * h, 0);
    sleeve.lineTo(0.026 * h, -0.274 * h);
    sleeve.absarc(0, -0.274 * h, 0.026 * h, 0, Math.PI, true);
    sleeve.lineTo(-0.026 * h, 0);
    pivot.add(new Mesh(new ShapeGeometry(sleeve), new MeshBasicMaterial({ color: colour })));
    this.body.add(pivot);
    this.arms.push({ pivot, side });
  }

  place(x: number, y: number, z = 0): void {
    this.node.position.set(x, y, z);
  }

  /** Walking scissors the legs along the screen, the arms counter-swing; lift raises both arms overhead. */
  pose(p: Pose): void {
    const h = this.h;
    const sw = p.stride * Math.sin(p.phase);
    this.body.position.y = p.stride * Math.abs(Math.cos(p.phase)) * 0.012 * h;
    for (const leg of this.legs) {
      const fx = (leg.hx + leg.side * 0.005 - leg.side * sw * 0.1) * h;
      const pos = leg.geo.getAttribute('position') as BufferAttribute;
      pos.setXYZ(0, leg.hx * h - 0.034 * h, 0.49 * h, 0);
      pos.setXYZ(1, fx - 0.028 * h, 0.02 * h, 0);
      pos.setXYZ(2, fx + 0.028 * h, 0.02 * h, 0);
      pos.setXYZ(3, leg.hx * h + 0.034 * h, 0.49 * h, 0);
      pos.needsUpdate = true;
      leg.geo.computeBoundingSphere();
      leg.shoe.position.x = fx - 0.008 * h;
      leg.shoe.position.y = 0.012 * h;
    }
    for (const arm of this.arms) {
      const swing = arm.side * (sw * 0.22 - 0.04);
      arm.pivot.rotation.z = swing + (arm.side * 2.9 - swing) * p.lift;
    }
  }
}
