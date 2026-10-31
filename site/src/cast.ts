import type { Group, Mesh } from 'three';
import { Person, type Look } from './person';
import { walkAt, type Waypoint } from './walk';
import { lerp, seg, ss } from './ease';
import { box, solid } from './solid';
import { tri } from './palette';

export interface Actor {
  person: Person;
  at(t: number): { x: number; y: number };
  update(t: number, lift?: number): void;
}

/** Everyone placed in the world, so the ending can empty the place. */
export const everyone: Person[] = [];

/** A person who follows a timed path; sampled, never simulated live. */
export function actor(root: Group, look: Look, path: Waypoint[]): Actor {
  const person = new Person(look);
  everyone.push(person);
  root.add(person.node);
  return {
    person,
    at: (t) => walkAt(path, t),
    update(t, lift = 0) {
      const s = walkAt(path, t);
      person.place(s.x, s.y);
      person.pose({ stride: s.stride, phase: s.phase, lift });
    },
  };
}

/** An upright memory card, standing across the chest like a file card in a drawer. */
export function card(colour: string, width = 0.9): Mesh {
  return solid([[box(-0.025, -width / 2, 0, 0.05, width, 0.55), tri(colour, 0.3, 0.2)]]);
}

/**
 * Files a card held by a standing person into a slot: it rises overhead, travels over the open chest
 * and is lowered in. Returns how far the arms are raised.
 */
export function fileCard(c: Mesh, from: { x: number; y: number }, slot: { x: number; y: number; z: number }, t: number, t0: number): number {
  const up = ss(seg(t, t0, t0 + 0.7));
  const across = ss(seg(t, t0 + 0.6, t0 + 1.5));
  const down = ss(seg(t, t0 + 1.4, t0 + 2.1));
  c.visible = t >= t0;
  c.position.set(lerp(from.x, slot.x, across), lerp(from.y, slot.y, across), lerp(lerp(1.05, 2.05, up), slot.z, down));
  return up * (1 - ss(seg(t, t0 + 1.5, t0 + 2.3)));
}
