import { Group } from 'three';
import { C, tri } from './palette';
import { box, fade, solid } from './solid';
import { seg, ss } from './ease';
import { card } from './cast';

const D = 1.2;
const H = 0.8;
const WALL = 0.08;
const FLOOR = 0.12;
export const SLOT_GAP = 0.34;

/**
 * A long low memory chest along x, cut open on top. Its lid is its own solid with a paper underside,
 * hinged on the far (-y) edge so it opens away from the camera.
 */
export class Chest {
  readonly node = new Group();
  readonly body = new Group();
  readonly lid = new Group();
  readonly x0: number;
  readonly yc: number;

  constructor(x0: number, length: number, yc: number, cardColour: string | null, cards: number) {
    this.x0 = x0;
    this.yc = yc;
    const y0 = yc - D / 2;
    const x1 = x0 + length;
    this.node.add(this.body);
    this.body.add(
      solid([
        [box(x0 + WALL, y0 + WALL, 0, length - 2 * WALL, D - 2 * WALL, FLOOR), C.carpetEdge],
        [box(x0, y0, 0, WALL, D, H), C.green],
        [box(x1 - WALL, y0, 0, WALL, D, H), C.green],
        [box(x0, y0, 0, length, WALL, H), C.green],
        [box(x0, y0 + D - WALL, 0, length, WALL, H), C.green],
      ]),
    );
    if (cardColour) {
      for (let i = 0; i < cards; i++) {
        const c = card(cardColour);
        c.position.set(this.slotX(i), yc, FLOOR);
        this.body.add(c);
      }
    }
    const lidTones = { ...tri(C.green), under: C.sheet };
    const lidMesh = solid([[box(-length / 2, 0, 0, length, D, 0.06), lidTones]]);
    this.lid.position.set(x0 + length / 2, y0, H);
    this.lid.add(lidMesh);
    this.node.add(this.lid);
  }

  slotX(i: number): number {
    return this.x0 + 0.35 + i * SLOT_GAP;
  }

  slot(i: number): { x: number; y: number; z: number } {
    return { x: this.slotX(i), y: this.yc, z: FLOOR };
  }

  /** Lid off: turns on its far hinge until paper side up, then glides away and is gone. */
  open(t: number, t0: number): void {
    const turn = ss(seg(t, t0, t0 + 1.1));
    const glide = ss(seg(t, t0 + 1.0, t0 + 1.9));
    this.lid.rotation.x = turn * (Math.PI - 0.06);
    this.lid.position.y = this.yc - D / 2 - glide * 1.8;
    fade(this.lid, 1 - glide);
  }
}
