import type { AdapterStatus, SystemStatus } from '../types';

export function errorMessage(err: unknown): string {
  if (err instanceof Error) {
    return err.message;
  }
  return String(err);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KiB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}

export function formatDuration(value: number | null): string {
  if (typeof value !== 'number') {
    return 'time pending';
  }
  if (value < 60) {
    return `${value.toFixed(1)}s`;
  }
  return `${Math.round(value / 60)}m`;
}

export function shortHash(value: string): string {
  return value.slice(0, 8);
}

export function formatOptimizer(adapter: AdapterStatus): string {
  if (adapter.optimizer === 'paged_adamw_8bit') {
    return 'paged 8-bit AdamW';
  }
  return adapter.optimizer_family ?? adapter.optimizer ?? 'optimizer pending';
}

export function formatFramework(value: string): string {
  if (value === 'unsloth_patched_transformers_peft') {
    return 'Unsloth patch + PEFT';
  }
  return value;
}

export function formatCheckpointing(adapter: AdapterStatus): string {
  if (adapter.gradient_checkpointing_mode === 'unsloth') {
    return 'ckpt unsloth';
  }
  return adapter.gradient_checkpointing ? 'ckpt on' : 'ckpt pending';
}

export function formatRuntimeDetail(status: SystemStatus | null): string {
  const model = status?.runtime.model_id ?? 'Qwen/Qwen3.5-9B';
  const adapter = status?.runtime.adapter_kind?.replaceAll('_', '-');
  return adapter ? `${model} · ${adapter}` : model;
}

export function formatVram(status: SystemStatus | null): string {
  const total = status?.runtime.vram_total_mb;
  const used = status?.runtime.vram_used_mb;
  if (typeof total === 'number' && typeof used === 'number') {
    return `${used} / ${total} MiB`;
  }
  return status?.runtime.cuda ?? 'CUDA';
}

export function formatStamp(iso: string | null): string {
  if (!iso) {
    return 'no time given';
  }
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
}

export function formatAgo(iso: string | null): string {
  if (!iso) {
    return 'undated';
  }
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) {
    return 'just now';
  }
  const units: Array<[number, string]> = [[3600, 'h'], [86400, 'd'], [2592000, 'mo'], [31536000, 'y']];
  for (const [size, name] of units.slice().reverse()) {
    if (seconds >= size) {
      return `${Math.floor(seconds / size)}${name} ago`;
    }
  }
  return `${Math.floor(seconds / 60)}m ago`;
}
