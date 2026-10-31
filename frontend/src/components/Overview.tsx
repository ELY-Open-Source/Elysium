import { formatNumber, formatRuntimeDetail, formatVram, plural } from '../lib/format';
import type { AdapterStatus, SystemStatus } from '../types';
import { Store } from './Store';
import { FloorWord, Quiet } from './ui';

interface Props {
  status: SystemStatus | null;
  adapters: AdapterStatus[] | null;
  lit: string | null;
  revision: number;
  onPick: (holder: string) => void;
}

/** The opening view: the store as a room, and four numbers about the machine that keeps it. */
export function Overview({ status, adapters, lit, revision, onPick }: Props) {
  return (
    <section id="store" className="overview" aria-labelledby="store-title">
      <div className="overview-words">
        <FloorWord text="往世乐土" />
        <h1 id="store-title">Elysian</h1>
        <p className="lede">A local memory you can see. Each shelf is a person. Click one to read what they know.</p>
      </div>
      <Store lit={lit} revision={revision} onPick={onPick} />
      {status ? <Status status={status} adapters={adapters} /> : <Quiet>Reading status.</Quiet>}
    </section>
  );
}

function Status({ status, adapters }: { status: SystemStatus; adapters: AdapterStatus[] | null }) {
  const bound = adapters?.filter((adapter) => adapter.cartridge_bound).length;
  const { memory, runtime } = status;
  const items: Array<[string, string, string]> = [
    ['Runtime', runtime.available ? 'ready' : 'offline', formatRuntimeDetail(status)],
    ['GPU', runtime.gpu_name ?? 'none seen', formatVram(status)],
    ['Library', formatNumber(memory.library_token_equivalent), `token eq · ${formatNumber(memory.active_token_equivalent)} open`],
    ['Cartridges', String(memory.cartridges), bound === undefined ? 'reading adapters' : `${plural(bound, 'adapter')} bound`],
  ];
  return (
    <dl className="status" aria-label="system status">
      {items.map(([term, value, detail]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>
            <strong>{value}</strong>
            <small>{detail}</small>
          </dd>
        </div>
      ))}
      <div className="status-version">
        <dt>Version</dt>
        <dd>
          <small>
            v{status.version} · {status.data_home}
          </small>
        </dd>
      </div>
    </dl>
  );
}
