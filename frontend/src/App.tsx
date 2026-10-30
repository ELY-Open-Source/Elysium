import { Activity, Archive, Database, Gauge, RefreshCw, Server } from 'lucide-react';
import { useEffect, useState } from 'react';

import { getAdapters, getStatus, readToken, writeToken } from './api';
import { AdapterPanel } from './components/AdapterPanel';
import { CartridgePanel } from './components/CartridgePanel';
import { CompilerPanel } from './components/CompilerPanel';
import { IngestPanel } from './components/IngestPanel';
import { MemoryPanel } from './components/MemoryPanel';
import { ProofPanel } from './components/ProofPanel';
import { SensesPanel } from './components/SensesPanel';
import { Kpi, Panel, Quiet } from './components/ui';
import { errorMessage, formatBytes, formatNumber, formatRuntimeDetail, formatVram } from './lib/format';
import type { AdapterStatus, CacheLayerStatus, SystemStatus } from './types';

export function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [adapters, setAdapters] = useState<AdapterStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(readToken);

  async function refresh() {
    const [nextStatus, nextAdapters] = await Promise.all([getStatus(), getAdapters()]);
    setStatus(nextStatus);
    setAdapters(nextAdapters);
  }

  useEffect(() => {
    let cancelled = false;
    async function loadInitial() {
      try {
        const [nextStatus, nextAdapters] = await Promise.all([getStatus(), getAdapters()]);
        if (!cancelled) {
          setStatus(nextStatus);
          setAdapters(nextAdapters);
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

  async function refreshQuietly() {
    try {
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const layers: CacheLayerStatus[] = status?.memory.layers ?? [];
  const boundAdapters = adapters.filter((adapter) => adapter.cartridge_bound).length;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Elysian · 往世乐土 v4.0</p>
          <h1>Local VLM Context OS</h1>
        </div>
        <div className="topbar-actions">
          <input
            className="token-input"
            type="password"
            value={token}
            placeholder="写入令牌"
            aria-label="写入令牌"
            title="服务器设置了 ELYSIAN_AUTH_TOKEN 时，写入需要它"
            onChange={(event) => {
              setToken(event.target.value);
              writeToken(event.target.value);
            }}
          />
          <button
            className="icon-button"
            title="Refresh status"
            onClick={() => refreshQuietly()}
          >
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      {error && <div className="error-line">{error}</div>}

      <section className="kpi-grid" aria-label="system status">
        <Kpi
          icon={<Server size={18} />}
          label="Runtime"
          value={status?.runtime.available ? 'ready' : 'offline'}
          detail={formatRuntimeDetail(status)}
        />
        <Kpi
          icon={<Gauge size={18} />}
          label="GPU"
          value={status?.runtime.gpu_name ?? 'unknown'}
          detail={formatVram(status)}
        />
        <Kpi
          icon={<Database size={18} />}
          label="Library"
          value={formatNumber(status?.memory.library_token_equivalent ?? 0)}
          detail={`${formatNumber(status?.memory.active_token_equivalent ?? 0)} token eq open`}
        />
        <Kpi
          icon={<Archive size={18} />}
          label="Cartridges"
          value={String(status?.memory.cartridges ?? 0)}
          detail={`${boundAdapters} adapters bound`}
        />
      </section>

      <section className="workspace-grid">
        <MemoryPanel onChanged={refreshQuietly} />
        <CartridgePanel onChanged={refreshQuietly} />
        <CompilerPanel onChanged={refreshQuietly} />
        <IngestPanel onChanged={refreshQuietly} />
        <SensesPanel senses={status?.senses ?? null} />
        <Panel title="Cache Trace" icon={<Activity size={17} />}>
          <div className="trace-list">
            {layers.map((layer) => (
              <div key={layer.layer} className="trace-row">
                <span>{layer.layer}</span>
                <meter
                  min={0}
                  max={Math.max(1, layer.hit_count + layer.miss_count)}
                  value={layer.hit_count}
                />
                <small>{formatBytes(layer.bytes_estimate)}</small>
              </div>
            ))}
            {layers.length === 0 && <Quiet>Waiting for retrieval</Quiet>}
          </div>
        </Panel>
        <AdapterPanel adapters={adapters} />
        <ProofPanel />
      </section>
    </main>
  );
}
