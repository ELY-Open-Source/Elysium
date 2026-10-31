import type {
  AdapterLoadReport,
  AdapterStatus,
  AnswerResponse,
  AtomPage,
  CartridgeManifest,
  EvidenceAtom,
  ForgetReport,
  HashHopProof,
  Holder,
  IngestResponse,
  Modality,
  MountState,
  ProofSuiteReport,
  RuntimeProfile,
  SearchFilters,
  SearchResult,
  SystemStatus,
} from './types';

const TOKEN_KEY = 'elysian_token';

/** The write token lives in the browser, not in the bundle: a served page must not ship the owner's secret. */
export function readToken(): string {
  return window.localStorage.getItem(TOKEN_KEY) ?? '';
}

export function writeToken(token: string): void {
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

/** A refusal from the API, with the status so a caller can tell "not there yet" from "broken". */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function refusal(response: Response): Promise<ApiError> {
  const body = await response.text();
  let detail = body || response.statusText;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (parsed.detail !== undefined) {
      detail = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail);
    }
  } catch {
    // A body that is not JSON is shown as the server sent it.
  }
  return new ApiError(response.status, `${response.status} ${new URL(response.url).pathname}: ${detail}`);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = readToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    throw await refusal(response);
  }
  return (await response.json()) as T;
}

function post<T>(url: string, body?: unknown): Promise<T> {
  if (body === undefined) {
    return request<T>(url, { method: 'POST' });
  }
  return request<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
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

export function listHolders(): Promise<Holder[]> {
  return request<Holder[]>('/api/holders');
}

export function ingestPath(path: string, cartridgeName: string): Promise<IngestResponse> {
  return post<IngestResponse>('/api/ingest/path', { path, cartridge_name: cartridgeName || null });
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
  return request<IngestResponse>(`/api/ingest/upload?${query.toString()}`, { method: 'POST', body: form });
}

export function askQuestion(question: string, profile: RuntimeProfile): Promise<AnswerResponse> {
  return post<AnswerResponse>('/api/chat', { question, profile });
}

export function search(query: string, filters: SearchFilters, topK = 8): Promise<SearchResult> {
  const named = Object.entries(filters).filter(([, value]) => value !== '' && value !== null && value !== undefined);
  return post<SearchResult>('/api/search', { query, top_k: topK, filters: Object.fromEntries(named) });
}

export interface AtomQuery {
  limit: number;
  cursor?: string;
  modality?: Modality | '';
  holder?: string;
}

export function listAtoms(options: AtomQuery): Promise<AtomPage> {
  const query = new URLSearchParams({ limit: String(options.limit) });
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

export function remember(text: string, scenario: string): Promise<EvidenceAtom> {
  return post<EvidenceAtom>('/api/memory', { text, scenario });
}

export function supersede(atomId: string, text: string, scenario: string): Promise<EvidenceAtom> {
  return post<EvidenceAtom>('/api/memory/supersede', { atom_id: atomId, text, scenario });
}

export function forget(atomId: string, reason: string): Promise<ForgetReport> {
  return post<ForgetReport>('/api/memory/forget', { atom_id: atomId, reason });
}

export function listCartridges(): Promise<CartridgeManifest[]> {
  return request<CartridgeManifest[]>('/api/cartridges');
}

export function getMounts(): Promise<MountState> {
  return request<MountState>('/api/mounts');
}

export type MountVerb = 'mount' | 'switch' | 'unmount';

export function changeMount(cartridgeId: string, verb: MountVerb): Promise<CartridgeManifest | MountState> {
  return post<CartridgeManifest | MountState>(`/api/cartridges/${encodeURIComponent(cartridgeId)}/${verb}`);
}

export function runHashHop(kind: 'text' | 'visual', hops: number, tokenEquivalent: number): Promise<HashHopProof> {
  return post<HashHopProof>('/api/hashhop', { kind, hops, token_equivalent: tokenEquivalent });
}

export function runProofSuite(): Promise<ProofSuiteReport> {
  return post<ProofSuiteReport>('/api/proof-suite', { cartridge_id: null });
}

/** The latest suite, or null when this store has never run one (the API answers 404). */
export async function getLatestProofSuite(): Promise<ProofSuiteReport | null> {
  try {
    return await request<ProofSuiteReport>('/api/proof-suite/latest');
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}
