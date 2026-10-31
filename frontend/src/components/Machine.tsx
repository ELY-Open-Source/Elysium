
import { getRuntimeAdapters } from '../api';
import { formatBytes, formatNumber, humanize, plural } from '../lib/format';
import { useResource } from '../lib/hooks';
import type { AdapterStatus, SenseStatus, SystemStatus } from '../types';
import { AdapterCards } from './AdapterCards';
import { Fault, Quiet, Section, State } from './ui';

interface Props {
  status: SystemStatus | null;
  adapters: AdapterStatus[] | null;
  revision: number;
}

/** What the machine can perceive, what it has cached, and which adapters it would load and why. */
export function Machine({ status, adapters, revision }: Props) {
  const load = useResource(getRuntimeAdapters, revision);

  return (
    <Section id="machine" lede="What it can see and hear. What it keeps warm. Which adapters it loads, and why the rest wait.">
      <h3>Senses</h3>
      {status ? <Senses senses={status.senses} /> : <Quiet>Waiting for status.</Quiet>}

      <h3>Cache trace</h3>
      <div className="ledger">
        {status?.memory.layers.map((layer) => (
          <div key={layer.layer} className="ledger-row">
            <span>{humanize(layer.layer)}</span>
            <meter min={0} max={Math.max(1, layer.hit_count + layer.miss_count)} value={layer.hit_count} />
            <small>
              {layer.hit_count} hits · {layer.miss_count} misses · {formatBytes(layer.bytes_estimate)}
            </small>
          </div>
        ))}
        {status?.memory.layers.length === 0 && <Quiet>Nothing is cached until a retrieval runs.</Quiet>}
      </div>

      <h3>Adapter load states</h3>
      {load.value && (
        <p className="summary">
          {load.value.model_id} · {load.value.mounted.length} mounted
        </p>
      )}
      <div className="ledger" data-testid="adapter-states">
        {load.value?.adapters.map((choice) => (
          <div className="ledger-row" key={choice.kind} data-state={choice.state}>
            <span>{humanize(choice.kind)}</span>
            <State value={choice.state} />
            <small title={choice.path ?? undefined}>{choice.reason}</small>
          </div>
        ))}
      </div>
      <Fault text={load.error} />

      <h3>Trained adapters</h3>
      {adapters && <AdapterCards adapters={adapters} />}
    </Section>
  );
}

function Senses({ senses }: { senses: SenseStatus }) {
  const pictures =
    `${plural(senses.picture_atoms, 'picture')} in the store` +
    (senses.picture_bytes_missing > 0 ? `, ${formatNumber(senses.picture_bytes_missing)} with no bytes behind them` : '');
  const rows: Array<[string, string, string]> = [
    ['dense vectors', senses.dense, `${formatNumber(senses.dense_covered)} of ${formatNumber(senses.dense_expected)} memories with words indexed`],
    ['picture embeddings', senses.visual, pictures],
    ['speech', senses.speech, plural(senses.audio_atoms, 'audio atom')],
    ['captioning', senses.captioning, 'writes what a picture shows into its text'],
  ];
  return (
    <>
      <div className="ledger">
        {rows.map(([label, state, detail]) => (
          <div className="ledger-row" key={label}>
            <span>{label}</span>
            <State value={state} />
            <small>{detail}</small>
          </div>
        ))}
      </div>
      <p className="facts-line">
        <span title={senses.clip_path ?? undefined}>{senses.clip_path ? `CLIP ${senses.clip_path}` : 'No CLIP snapshot set.'}</span>{' '}
        <span title={senses.asr_path ?? undefined}>{senses.asr_path ? `ASR ${senses.asr_path}` : 'No speech snapshot set.'}</span>{' '}
        <span title={senses.vlm_url ?? undefined}>{senses.vlm_url ? `VLM ${senses.vlm_url}` : 'No captioning model served.'}</span>
      </p>
    </>
  );
}
