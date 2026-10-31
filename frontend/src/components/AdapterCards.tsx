import {
  formatBytes,
  formatCheckpointing,
  formatDuration,
  formatFramework,
  formatNumber,
  formatOptimizer,
  humanize,
  shortHash,
} from '../lib/format';
import type { AdapterStatus } from '../types';
import { Quiet, State } from './ui';

/** Every trained adapter with the facts that prove it was trained, not just named. */
export function AdapterCards({ adapters }: { adapters: AdapterStatus[] }) {
  if (adapters.length === 0) {
    return <Quiet>No adapter is trained yet.</Quiet>;
  }
  return (
    <div className="rows">
      {adapters.map((adapter) => (
        <article className="adapter" key={adapter.adapter_id}>
          <header>
            <h4>{humanize(adapter.kind)}</h4>
            {adapter.cartridge_bound && <State value="bound" />}
          </header>
          <p className="mono">{adapter.base_model}</p>
          <p className="facts-line">
            {[
              adapter.training_method,
              adapter.precision,
              formatFramework(adapter.framework),
              formatOptimizer(adapter),
              formatCheckpointing(adapter),
              adapter.triton_version ? `triton ${adapter.triton_version}` : 'no triton',
              formatBytes(adapter.weight_bytes),
              `${formatNumber(adapter.trainable_params)} params`,
              adapter.final_loss === null ? 'no final loss' : `loss ${adapter.final_loss.toFixed(3)}`,
              `${adapter.training_trace_steps}/${adapter.max_steps} steps traced`,
              `${formatNumber(adapter.optimizer_update_count)} updates`,
              adapter.loss_delta === null ? 'no loss delta' : `loss delta ${adapter.loss_delta.toFixed(3)}`,
              adapter.bf16 ? 'CUDA bf16' : 'not bf16',
              `${formatNumber(adapter.adapter_lora_tensor_count)} LoRA tensors`,
              `${formatNumber(adapter.adapter_nonzero_elements)} nonzero`,
              adapter.adapter_weights_finite ? 'finite weights' : 'weights not finite',
              adapter.adapter_weight_sha256 ? `sha ${shortHash(adapter.adapter_weight_sha256)}` : 'no weight hash',
              formatDuration(adapter.training_wall_seconds),
            ].join(' · ')}
          </p>
        </article>
      ))}
    </div>
  );
}
