import { CheckCircle, Cpu } from 'lucide-react';
import { useEffect, useState } from 'react';

import { getRuntimeAdapters } from '../api';
import type { AdapterLoadReport, AdapterStatus } from '../types';
import {
  errorMessage,
  formatBytes,
  formatCheckpointing,
  formatDuration,
  formatFramework,
  formatNumber,
  formatOptimizer,
  shortHash,
} from '../lib/format';
import { Panel, Quiet } from './ui';

export function AdapterPanel({ adapters }: { adapters: AdapterStatus[] }) {
  const [load, setLoad] = useState<AdapterLoadReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadStates() {
      try {
        const next = await getRuntimeAdapters();
        if (!cancelled) {
          setLoad(next);
        }
      } catch (err) {
        if (!cancelled) {
          setError(errorMessage(err));
        }
      }
    }
    void loadStates();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Panel title="Adapter Matrix" icon={<Cpu size={17} />}>
      {load && (
        <div className="metric-strip">
          <span>{load.model_id}</span>
          <span>{load.mounted.length} mounted</span>
        </div>
      )}
      <div className="layer-list">
        {(load?.adapters ?? []).map((choice) => (
          <div className="layer-row" key={choice.kind}>
            <span>{choice.kind.replaceAll('_', '-')}</span>
            <strong>{choice.state}</strong>
            <small title={choice.path ?? undefined}>{choice.reason}</small>
          </div>
        ))}
        {!load && <Quiet>Load states unavailable.</Quiet>}
      </div>
      <div className="adapter-list">
        {adapters.map((adapter) => (
          <div className="adapter-row" key={adapter.adapter_id}>
            <header>
              <span>{adapter.kind.replaceAll('_', '-')}</span>
              {adapter.cartridge_bound && <CheckCircle size={16} aria-label="bound" />}
            </header>
            <strong>{adapter.base_model}</strong>
            <div className="adapter-metrics">
              <small>{adapter.training_method}</small>
              <small>{adapter.precision}</small>
              <small title={adapter.unsloth_model_type ?? adapter.framework ?? undefined}>
                {formatFramework(adapter.framework)}
              </small>
              <small title={adapter.optimizer_family ?? adapter.optimizer ?? undefined}>
                {formatOptimizer(adapter)}
              </small>
              <small title={adapter.gradient_checkpointing_mode ?? undefined}>{formatCheckpointing(adapter)}</small>
              <small title={adapter.triton_version ?? undefined}>
                {adapter.triton_version ? `triton ${adapter.triton_version}` : 'triton pending'}
              </small>
              <small>{formatBytes(adapter.weight_bytes)}</small>
              <small>{formatNumber(adapter.trainable_params)} params</small>
              <small>{adapter.final_loss?.toFixed(3) ?? 'loss pending'}</small>
              <small>
                {adapter.training_trace_steps}/{adapter.max_steps} trace
              </small>
              <small>{formatNumber(adapter.optimizer_update_count)} updates</small>
              <small>
                {adapter.loss_delta == null ? 'loss delta pending' : `loss delta ${adapter.loss_delta.toFixed(3)}`}
              </small>
              <small>{adapter.bf16 ? 'cuda bf16' : 'precision pending'}</small>
              <small>{formatNumber(adapter.adapter_lora_tensor_count)} LoRA tensors</small>
              <small>{formatNumber(adapter.adapter_nonzero_elements)} nonzero</small>
              <small>{adapter.adapter_weights_finite ? 'finite weights' : 'weights pending'}</small>
              <small>
                {adapter.adapter_weight_sha256 ? `sha ${shortHash(adapter.adapter_weight_sha256)}` : 'sha pending'}
              </small>
              <small>{formatDuration(adapter.training_wall_seconds)}</small>
            </div>
          </div>
        ))}
        {adapters.length === 0 && <Quiet>No adapters found</Quiet>}
      </div>
      {error && <div className="error-line">{error}</div>}
    </Panel>
  );
}
