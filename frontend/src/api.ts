import type {
  AdapterLoadReport,
  AdapterStatus,
  AnswerResponse,
  AtomPage,
  CartridgeManifest,
  ForgetReport,
  HashHopProof,
  IngestResponse,
  MountState,
  ProofSuiteReport,
  RuntimeProfile,
  RuntimeProfileReport,
  SearchFilters,
  SearchResult,
  SystemStatus,
} from './types';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail));
  }
  return (await response.json()) as T;
}

export function getStatus(): Promise<SystemStatus> {
  return request<SystemStatus>('/api/status');
}

export function getAdapters(): Promise<AdapterStatus[]> {
  return request<AdapterStatus[]>('/api/adapters');
}

export function getRuntimeAdapters(): Promise<AdapterLoadReport> {
  return request<AdapterLoadReport>('/api/runtime/adapters');
}

export function getRuntimeProfiles(): Promise<RuntimeProfileReport> {
  return request<RuntimeProfileReport>('/api/runtime/profiles');
}

export function ingestPath(path: string, cartridgeName: string): Promise<IngestResponse> {
  return request<IngestResponse>('/api/ingest/path', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, cartridge_name: cartridgeName || null }),
  });
}

export function uploadFiles(files: File[], cartridgeName: string): Promise<IngestResponse> {
  const form = new FormData();
  for (const file of files) {
    form.append('files', file);
  }
  const query = new URLSearchParams();
  if (cartridgeName) {
    query.set('cartridge_name', cartridgeName);
  }
  return request<IngestResponse>(`/api/ingest/upload?${query.toString()}`, {
    method: 'POST',
    body: form,
  });
}

export function askQuestion(question: string, profile: RuntimeProfile): Promise<AnswerResponse> {
  return request<AnswerResponse>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, profile }),
  });
}

export function search(query: string, filters: SearchFilters = {}, topK = 8): Promise<SearchResult> {
  const compact: SearchFilters = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value !== '' && value !== null && value !== undefined) {
      compact[key as keyof SearchFilters] = value;
    }
  }
  return request<SearchResult>('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK, filters: compact }),
  });
}

export function listAtoms(options: { limit?: number; cursor?: string; modality?: string; holder?: string } = {}): Promise<AtomPage> {
  const query = new URLSearchParams({ limit: String(options.limit ?? 12) });
  if (options.cursor) {
    query.set('cursor', options.cursor);
  }
  if (options.modality) {
    query.set('modality', options.modality);
  }
  if (options.holder) {
    query.set('holder', options.holder);
  }
  return request<AtomPage>(`/api/atoms?${query.toString()}`);
}

export function atomImageUrl(atomId: string): string {
  return `/api/atoms/${encodeURIComponent(atomId)}/image`;
}

export function remember(text: string, scenario: string): Promise<unknown> {
  return request<unknown>('/api/memory', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, scenario: scenario || null }),
  });
}

export function forget(atomId: string, reason = ''): Promise<ForgetReport> {
  return request<ForgetReport>('/api/memory/forget', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ atom_id: atomId, reason }),
  });
}

export function listCartridges(): Promise<CartridgeManifest[]> {
  return request<CartridgeManifest[]>('/api/cartridges');
}

export function getMounts(): Promise<MountState> {
  return request<MountState>('/api/mounts');
}

export function mountCartridge(cartridgeId: string): Promise<CartridgeManifest> {
  return request<CartridgeManifest>(`/api/cartridges/${encodeURIComponent(cartridgeId)}/mount`, { method: 'POST' });
}

export function switchCartridge(cartridgeId: string): Promise<CartridgeManifest> {
  return request<CartridgeManifest>(`/api/cartridges/${encodeURIComponent(cartridgeId)}/switch`, { method: 'POST' });
}

export function unmountCartridge(cartridgeId: string): Promise<MountState> {
  return request<MountState>(`/api/cartridges/${encodeURIComponent(cartridgeId)}/unmount`, { method: 'POST' });
}

export function runHashHop(kind: 'text' | 'visual', hops: number, tokenEquivalent: number): Promise<HashHopProof> {
  return request<HashHopProof>('/api/hashhop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, hops, token_equivalent: tokenEquivalent }),
  });
}

export function runProofSuite(cartridgeId?: string): Promise<ProofSuiteReport> {
  return request<ProofSuiteReport>('/api/proof-suite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cartridge_id: cartridgeId ?? null }),
  });
}

export function getLatestProofSuite(): Promise<ProofSuiteReport> {
  return request<ProofSuiteReport>('/api/proof-suite/latest');
}
