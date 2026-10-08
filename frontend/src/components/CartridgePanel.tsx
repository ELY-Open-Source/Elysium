import { Archive, Play, Square, SwitchCamera } from 'lucide-react';
import { useEffect, useState } from 'react';

import { getMounts, listCartridges, mountCartridge, switchCartridge, unmountCartridge } from '../api';
import type { CartridgeManifest, MountState } from '../types';
import { errorMessage, formatNumber, shortHash } from '../lib/format';
import { Panel, Quiet } from './ui';

export function CartridgePanel({ onChanged }: { onChanged: () => void }) {
  const [cartridges, setCartridges] = useState<CartridgeManifest[]>([]);
  const [mounts, setMounts] = useState<MountState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [nextCartridges, nextMounts] = await Promise.all([listCartridges(), getMounts()]);
      setCartridges(nextCartridges);
      setMounts(nextMounts);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function loadInitial() {
      try {
        const [nextCartridges, nextMounts] = await Promise.all([listCartridges(), getMounts()]);
        if (!cancelled) {
          setCartridges(nextCartridges);
          setMounts(nextMounts);
        }
      } catch (err) {
        if (!cancelled) {
          setError(errorMessage(err));
        }
      }
    }
    void loadInitial();
    return () => {
      cancelled = true;
    };
  }, []);

  async function act(cartridgeId: string, verb: 'mount' | 'switch' | 'unmount') {
    setBusy(`${verb}-${cartridgeId}`);
    setError(null);
    try {
      if (verb === 'mount') {
        await mountCartridge(cartridgeId);
      } else if (verb === 'switch') {
        await switchCartridge(cartridgeId);
      } else {
        await unmountCartridge(cartridgeId);
      }
      setNotice(`${verb} ${cartridgeId}`);
      await load();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel title="Cartridges" icon={<Archive size={17} />}>
      <div className="metric-strip">
        <span>{mounts?.mounted.length ?? 0} mounted</span>
        <span>{mounts?.scoped ? 'search is scoped' : 'search sees the whole store'}</span>
      </div>
      <div className="adapter-list">
        {cartridges.map((cartridge) => {
          const mounted = mounts?.mounted.includes(cartridge.cartridge_id) ?? false;
          return (
            <article className="adapter-row" key={cartridge.cartridge_id}>
              <header>
                <span>{cartridge.name}</span>
                {mounted && <span className="proof-pill passed">mounted</span>}
              </header>
              <strong>{cartridge.cartridge_id}</strong>
              <div className="adapter-metrics">
                <small>{formatNumber(cartridge.atom_count)} atoms</small>
                <small>{formatNumber(cartridge.source_count)} sources</small>
                <small>{formatNumber(cartridge.token_equivalent)} token eq</small>
                <small>{cartridge.model_base}</small>
                <small title={cartridge.dna ?? undefined}>
                  {cartridge.dna ? `dna ${shortHash(cartridge.dna)}` : 'dna pending'}
                </small>
                <small>
                  {cartridge.kv_fingerprint
                    ? 'kv fingerprint pinned'
                    : 'no kv fingerprint: mounting must re-check this machine'}
                </small>
              </div>
              <div className="button-row">
                <button
                  className="action-button secondary"
                  onClick={() => act(cartridge.cartridge_id, 'mount')}
                  disabled={busy !== null || mounted}
                >
                  <Play size={15} />
                  Mount
                </button>
                <button
                  className="action-button secondary"
                  onClick={() => act(cartridge.cartridge_id, 'switch')}
                  disabled={busy !== null}
                >
                  <SwitchCamera size={15} />
                  Switch
                </button>
                <button
                  className="action-button secondary"
                  onClick={() => act(cartridge.cartridge_id, 'unmount')}
                  disabled={busy !== null || !mounted}
                >
                  <Square size={15} />
                  Unmount
                </button>
              </div>
            </article>
          );
        })}
        {cartridges.length === 0 && <Quiet>No cartridge has been finalized yet.</Quiet>}
      </div>
      {notice && <div className="metric-strip"><span>{notice}</span></div>}
      {error && <div className="error-line">{error}</div>}
    </Panel>
  );
}
