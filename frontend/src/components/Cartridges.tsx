import { changeMount, getMounts, listCartridges, type MountVerb } from '../api';
import { plural, shortHash } from '../lib/format';
import { useAction, useResource } from '../lib/hooks';
import type { CartridgeManifest } from '../types';
import { Fault, Notice, Quiet, Section, State } from './ui';

const DONE: Record<MountVerb, string> = { mount: 'Mounted', switch: 'Switched to', unmount: 'Unmounted' };
const loadListing = () => Promise.all([listCartridges(), getMounts()]);

/** Cartridges are scopes: mount one and search sees only what it holds, if this machine may load it. */
export function Cartridges({ revision, onChanged }: { revision: number; onChanged: () => void }) {
  const listing = useResource(loadListing, revision);
  const action = useAction();
  const [cartridges, mounts] = listing.value ?? [null, null];

  function act(cartridge: CartridgeManifest, verb: MountVerb) {
    void action.run(`${verb}-${cartridge.cartridge_id}`, async () => {
      await changeMount(cartridge.cartridge_id, verb);
      onChanged();
      return `${DONE[verb]} ${cartridge.name}.`;
    });
  }

  return (
    <Section id="cartridges" lede="A cartridge is a sealed set of memories. Mount it to scope search. The machine checks it may.">
      {mounts && (
        <p className="summary">
          {plural(mounts.mounted.length, 'cartridge')} mounted. {mounts.scoped ? 'Search is scoped to them.' : 'Search sees the whole store.'}
        </p>
      )}
      <div className="rows">
        {cartridges?.map((cartridge) => {
          const mounted = mounts?.mounted.includes(cartridge.cartridge_id) === true;
          return (
            <article className="cartridge" key={cartridge.cartridge_id} data-cartridge={cartridge.name}>
              <header>
                <h3>{cartridge.name}</h3>
                {mounted && <State value="mounted" />}
              </header>
              <p className="mono">{cartridge.cartridge_id}</p>
              <p className="facts-line">
                {plural(cartridge.atom_count, 'atom')} · {plural(cartridge.source_count, 'source')} · {plural(cartridge.token_equivalent, 'token')} ·{' '}
                {cartridge.model_base} ·{' '}
                <span title={cartridge.dna ?? undefined}>{cartridge.dna ? `dna ${shortHash(cartridge.dna)}` : 'no dna yet'}</span> ·{' '}
                {cartridge.kv_fingerprint ? 'kv fingerprint pinned' : 'no kv fingerprint: mounting re-checks this machine'}
              </p>
              <div className="row">
                <button type="button" className="solid" onClick={() => act(cartridge, 'mount')} disabled={action.busy !== null || mounted}>
                  Mount
                </button>
                <button type="button" className="quiet-button" onClick={() => act(cartridge, 'switch')} disabled={action.busy !== null}>
                  Switch
                </button>
                <button type="button" className="quiet-button" onClick={() => act(cartridge, 'unmount')} disabled={action.busy !== null || !mounted}>
                  Unmount
                </button>
              </div>
            </article>
          );
        })}
        {cartridges?.length === 0 && <Quiet>No cartridge is sealed yet.</Quiet>}
      </div>
      <Notice text={action.notice} />
      <Fault text={action.error} />
      <Fault text={listing.error} />
    </Section>
  );
}
