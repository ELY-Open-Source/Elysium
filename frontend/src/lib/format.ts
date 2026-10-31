import type { AdapterStatus, ForgetReport, SystemStatus } from '../types';

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function plural(count: number, word: string, many = `${word}s`): string {
  return `${formatNumber(count)} ${count === 1 ? word : many}`;
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
  if (value === null) {
    return 'no wall time';
  }
  return value < 60 ? `${value.toFixed(1)} s` : `${Math.round(value / 60)} min`;
}

export function shortHash(value: string): string {
  return value.slice(0, 8);
}

export function formatOptimizer(adapter: AdapterStatus): string {
  if (adapter.optimizer === 'paged_adamw_8bit') {
    return 'paged 8-bit AdamW';
  }
  return adapter.optimizer_family ?? adapter.optimizer ?? 'no optimizer recorded';
}

export function formatFramework(value: string): string {
  return value === 'unsloth_patched_transformers_peft' ? 'Unsloth patch + PEFT' : value;
}

export function formatCheckpointing(adapter: AdapterStatus): string {
  if (adapter.gradient_checkpointing_mode === 'unsloth') {
    return 'checkpointing: unsloth';
  }
  return adapter.gradient_checkpointing ? 'checkpointing on' : 'checkpointing off';
}

export function formatRuntimeDetail(status: SystemStatus): string {
  const adapter = status.runtime.adapter_kind?.replaceAll('_', '-');
  return adapter ? `${status.runtime.model_id} · ${adapter}` : status.runtime.model_id;
}

export function formatVram(status: SystemStatus): string {
  const { vram_total_mb: total, vram_used_mb: used, cuda } = status.runtime;
  if (total !== null && used !== null) {
    return `${used} / ${total} MiB`;
  }
  return cuda ? `CUDA ${cuda}, no memory reading` : 'no CUDA seen';
}

export function formatStamp(iso: string): string {
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z`;
}

export function formatAgo(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) {
    return 'just now';
  }
  const units: Array<[number, string]> = [
    [31536000, 'y'],
    [2592000, 'mo'],
    [86400, 'd'],
    [3600, 'h'],
  ];
  for (const [size, name] of units) {
    if (seconds >= size) {
      return `${Math.floor(seconds / size)}${name} ago`;
    }
  }
  return `${Math.floor(seconds / 60)}m ago`;
}

export function describeForget(report: ForgetReport): string {
  const parts = [
    plural(report.atoms_deleted, 'atom'),
    plural(report.edges_deleted, 'link'),
    plural(report.cache_entries_cleared, 'cache entry', 'cache entries'),
  ];
  if (report.semantic_cache_cleared) {
    parts.push(`${plural(report.semantic_cache_cleared, 'compiled context')} dropped`);
  }
  if (report.vectors_dropped) {
    parts.push(`${plural(report.vectors_dropped, 'dense vector')} dropped`);
  }
  if (report.visual_index_dropped) {
    parts.push('picture index dropped');
  }
  return `Forgotten: ${parts.join(', ')}.`;
}

export function humanize(value: string): string {
  return value.replaceAll('_', ' ');
}
