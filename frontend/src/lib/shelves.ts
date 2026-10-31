import { listAtoms, listHolders } from '../api';
import { MODALITIES, type Modality } from '../types';

/** One holder's row in the store; `counts[i]` is how many current memories of `modalities[i]` they hold. */
export interface Shelf {
  holder: string;
  counts: number[];
}

export interface StoreShape {
  shelves: Shelf[];
  others: Shelf | null;
  modalities: Modality[];
  total: number;
  lit: string | null;
}

/** Shelves shown at most; the rest of the store goes on one shelf for everyone else. */
export const MAX_SHELVES = 6;
const RECENT_WINDOW = 200;

async function count(holder: string, modality: Modality | ''): Promise<number> {
  return (await listAtoms({ limit: 1, holder, modality })).total;
}

/**
 * Counts the store by holder and modality through the browse API, which counts what the token may see.
 * Holders come from the registry, the newest memories and the lit holder; whatever they do not hold
 * lands on the "others" shelf, so the picture always adds up to the store.
 */
export async function loadStoreShape(lit: string | null): Promise<StoreShape> {
  const [registered, recent, totals] = await Promise.all([
    listHolders(),
    listAtoms({ limit: RECENT_WINDOW }),
    Promise.all(MODALITIES.map((modality) => count('', modality))),
  ]);
  const present = MODALITIES.filter((_, index) => totals[index] > 0);
  const names = new Set([...registered.map((entry) => entry.holder_id), ...recent.atoms.map((atom) => atom.holder_id)]);
  names.delete('');
  const held = await Promise.all([...names].map(async (holder) => ({ holder, total: await count(holder, '') })));
  const chosen = held
    .filter((entry) => entry.total > 0 || entry.holder === lit)
    .sort((a, b) => b.total - a.total)
    .slice(0, MAX_SHELVES)
    .map((entry) => entry.holder);
  if (lit && !chosen.includes(lit)) {
    chosen[Math.min(chosen.length, MAX_SHELVES - 1)] = lit;
  }
  const shelves = await Promise.all(
    chosen.map(async (holder) => {
      const counts = await Promise.all(present.map((modality) => count(holder, modality)));
      return { holder, counts };
    }),
  );
  const rest = present.map((modality, column) => {
    const shown = shelves.reduce((sum, shelf) => sum + shelf.counts[column], 0);
    return totals[MODALITIES.indexOf(modality)] - shown;
  });
  const others = rest.some((value) => value > 0) ? { holder: '', counts: rest } : null;
  return { shelves, others, modalities: present, total: totals.reduce((sum, value) => sum + value, 0), lit };
}
