import { Eye } from 'lucide-react';

import type { SenseStatus } from '../types';
import { formatNumber } from '../lib/format';
import { Panel, Quiet } from './ui';

export function SensesPanel({ senses }: { senses: SenseStatus | null }) {
  return (
    <Panel title="Senses" icon={<Eye size={17} />}>
      <div className="layer-list">
        {senses && (
          <>
            <SenseRow
              label="dense vectors"
              state={senses.dense}
              detail={`${formatNumber(senses.dense_covered)} of ${formatNumber(senses.dense_expected)} memories with words indexed`}
            />
            <SenseRow
              label="picture embeddings"
              state={senses.visual}
              detail={
                `${formatNumber(senses.picture_atoms)} pictures in the store` +
                (senses.picture_bytes_missing > 0
                  ? `, ${formatNumber(senses.picture_bytes_missing)} with no bytes behind them`
                  : '')
              }
            />
            <SenseRow
              label="speech"
              state={senses.speech}
              detail={`${formatNumber(senses.audio_atoms)} audio atoms`}
            />
            <SenseRow label="captioning" state={senses.captioning} detail="writes what a picture shows into its text" />
          </>
        )}
        {!senses && <Quiet>Waiting for status.</Quiet>}
      </div>
      {senses && (
        <div className="adapter-metrics">
          <small title={senses.clip_path ?? undefined}>{senses.clip_path ? `clip ${senses.clip_path}` : 'no CLIP snapshot configured'}</small>
          <small title={senses.asr_path ?? undefined}>{senses.asr_path ? `asr ${senses.asr_path}` : 'no speech snapshot configured'}</small>
          <small title={senses.vlm_url ?? undefined}>{senses.vlm_url ? `vlm ${senses.vlm_url}` : 'no captioning model served'}</small>
        </div>
      )}
    </Panel>
  );
}

function SenseRow({ label, state, detail }: { label: string; state: string; detail: string }) {
  return (
    <div className="layer-row">
      <span>{label}</span>
      <strong>{state}</strong>
      <small>{detail}</small>
    </div>
  );
}
