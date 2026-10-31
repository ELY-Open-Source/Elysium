import type { Key } from './stage';
import type { Person } from './person';

/** A person the visitor can point at; card names the <template> in index.html that holds their memory. */
export interface Hover {
  person: Person;
  card: string;
  label?: string;
}

/** One rule of the story: the DOM section it captions, its camera keys and a pure function of time. */
export interface Beat {
  id: string;
  start: number;
  settle: number;
  keys: Key[];
  hover: Hover[];
  update(t: number): void;
}

/** Film time, in seconds, at which each beat's caption takes over. */
export const T = {
  opening: 0,
  holders: 10,
  referral: 23,
  cost: 35,
  speed: 48,
  counter: 60,
  ending: 71,
  end: 80,
} as const;

/** Where each stop stands along the one road; the camera travels toward -x (up-right on screen). */
export const X = {
  opening: 0,
  holders: -48,
  referral: -96,
  cost: -146,
  speed: -198,
  counter: -248,
} as const;
