export type RuntimeProfile = 'live_demo' | 'extreme_context' | 'library_100m' | 'research_theater';

export interface RuntimeStatus {
  backend: string;
  model_id: string;
  available: boolean;
  detail: string;
  adapter_path: string | null;
  adapter_kind: string | null;
  adapter_id: string | null;
  adapter_sha256: string | null;
  gpu_name: string | null;
  cuda: string | null;
  vram_total_mb: number | null;
  vram_used_mb: number | null;
}

export interface CacheLayerStatus {
  layer: string;
  entries: number;
  bytes_estimate: number;
  hit_count: number;
  miss_count: number;
  last_event_at: string | null;
}

export interface MemoryStatus {
  active_atoms: number;
  active_token_equivalent: number;
  cartridges: number;
  library_token_equivalent: number;
  layers: CacheLayerStatus[];
}

export interface SenseStatus {
  dense: 'off' | 'missing' | 'behind' | 'current';
  dense_covered: number;
  dense_expected: number;
  picture_atoms: number;
  picture_bytes_missing: number;
  visual: 'absent' | 'stale' | 'ready';
  audio_atoms: number;
  speech: 'absent' | 'missing' | 'ready';
  captioning: 'absent' | 'missing' | 'ready';
  clip_path: string | null;
  asr_path: string | null;
  vlm_url: string | null;
}

export interface SystemStatus {
  app: string;
  version: string;
  runtime: RuntimeStatus;
  memory: MemoryStatus;
  senses: SenseStatus;
  profiles: Record<string, Record<string, unknown>>;
  data_home: string;
}

export interface AdapterStatus {
  name: string;
  kind: string;
  proof_version: number;
  training_method: string;
  precision: string;
  framework: string;
  base_model: string;
  path: string;
  adapter_id: string;
  sample_count: number;
  max_steps: number;
  trainable_params: number;
  final_loss: number | null;
  sha256: string;
  weight_bytes: number;
  safetensor_keys: number;
  cartridge_id: string | null;
  cartridge_bound: boolean;
  training_trace_path: string | null;
  training_trace_sha256: string | null;
  training_trace_steps: number;
  training_proof_path: string | null;
  training_proof_sha256: string | null;
  optimizer: string | null;
  optimizer_family: string | null;
  gradient_checkpointing: boolean;
  gradient_checkpointing_mode: string | null;
  autocast_dtype: string | null;
  unsloth_version: string | null;
  triton_version: string | null;
  xformers_version: string | null;
  unsloth_model_type: string | null;
  optimizer_update_count: number;
  max_optimizer_update_l2: number | null;
  loss_delta: number | null;
  training_summary_path: string | null;
  training_wall_seconds: number | null;
  training_device: string | null;
  bf16: boolean;
  torch_version: string | null;
  cuda_version: string | null;
  adapter_weight_sha256: string | null;
  adapter_tensor_count: number;
  adapter_lora_tensor_count: number;
  adapter_total_elements: number;
  adapter_nonzero_elements: number;
  adapter_max_abs: number | null;
  adapter_weights_finite: boolean;
}

export interface IngestResponse {
  source_count: number;
  atom_count: number;
  cartridge_id: string | null;
  token_equivalent: number;
}

export interface LayoutBox {
  x: number;
  y: number;
  w: number;
  h: number;
  page?: number | null;
  frame_second?: number | null;
}

export interface TrustScores {
  parser: number;
  ocr: number;
  model: number;
}

export const MODALITIES = [
  'text',
  'code',
  'image',
  'pdf_page',
  'pdf_region',
  'video_frame',
  'audio',
  'ui_screenshot',
  'mixed',
] as const;

export type Modality = (typeof MODALITIES)[number];

export type MemoryOrigin = 'self' | 'observed' | 'artifact' | 'third_party';

export type TimePrecision = 'instant' | 'minute' | 'hour' | 'day' | 'month' | 'year' | 'unknown';

export interface Visibility {
  scope: 'holder' | 'visible_to' | 'everyone';
  holders: string[];
  purpose: string | null;
}

export interface EvidenceAtom {
  atom_id: string;
  modality: Modality;
  source_id: string;
  source: string;
  ingested_at: string;
  text: string;
  image_ref: string | null;
  embedding_refs: string[];
  layout: LayoutBox | null;
  relations: string[];
  trust: TrustScores;
  token_equivalent: number;
  metadata: Record<string, unknown>;
  holder_id: string;
  origin: MemoryOrigin;
  scenario: string;
  event_time: string | null;
  event_time_end: string | null;
  event_time_precision: TimePrecision;
  event_time_source: string;
  valid_from: string | null;
  valid_to: string | null;
  supersedes: string[];
  visibility: Visibility;
  retention_until: string | null;
  quarantined: boolean;
  session_id: string;
  importance: number | null;
  recall_count: number;
  last_recalled_at: string | null;
  archived_at: string | null;
}

/** Mirrors transactive_schemas.Holder: a registered person, agent or service. */
export interface Holder {
  holder_id: string;
  name: string;
  kind: 'person' | 'agent' | 'service';
  knows_about: string[];
  contact: Record<string, string>;
  token_issued_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AtomPage {
  atoms: EvidenceAtom[];
  total: number;
  next_cursor: string | null;
}

export interface SearchFilters {
  holder?: string | null;
  as_holder?: string | null;
  scenario?: string | null;
  source_id?: string | null;
  modality?: Modality | null;
  since?: string | null;
  until?: string | null;
  min_trust?: number | null;
}

export interface RetrievalHit {
  atom: EvidenceAtom;
  sparse_score: number;
  dense_score: number;
  visual_score: number;
  graph_score: number;
  final_score: number;
}

export interface SearchResult {
  query: string;
  status: 'hits' | 'no_match';
  hits: RetrievalHit[];
  next_cursor: string | null;
}

export interface AnswerResponse {
  answer: string;
  citations: string[];
  context: {
    hits: RetrievalHit[];
    token_equivalent: number;
    cache_trace_id: string;
  };
  verifier: {
    cited_atom_ids: string[];
    missing_atom_ids: string[];
    citation_accuracy: number;
    contradiction_notes: string[];
    confidence: number;
  };
  runtime_backend: string;
}

export interface HashHopProof {
  proof_id: string;
  kind: string;
  hops: number;
  token_equivalent: number;
  query_id: string;
  expected_target_id: string;
  model_target_id: string | null;
  passed: boolean | null;
  artifacts: string[];
  created_at: string;
}

export interface ProofCheck {
  name: string;
  requirement: string;
  status: 'passed' | 'failed';
  evidence: string[];
  detail: string;
}

export interface ProofSuiteReport {
  proof_id: string;
  cartridge_id: string;
  status: 'passed' | 'failed';
  created_at: string;
  checks: ProofCheck[];
  artifacts: Record<string, string>;
  dna_before: string | null;
  dna_after: string | null;
}

export interface CartridgeManifest {
  cartridge_id: string;
  name: string;
  created_at: string;
  model_base: string;
  source_count: number;
  atom_count: number;
  token_equivalent: number;
  artifacts: Record<string, string>;
  kv_fingerprint: Record<string, unknown> | null;
  dna: string | null;
}

export interface MountState {
  mounted: string[];
  scoped: boolean;
}

export interface AdapterChoice {
  kind: string;
  state: 'loaded' | 'available' | 'deferred' | 'missing';
  reason: string;
  path: string | null;
  adapter_id: string | null;
  base_model: string | null;
  origin: 'library' | 'cartridge' | null;
  cartridge_id: string | null;
  shadowed: boolean;
}

export interface AdapterLoadReport {
  model_id: string;
  mounted: string[];
  adapters: AdapterChoice[];
}

export interface RuntimeLaunchProfile {
  name: string;
  runtime: string;
  role: string;
  context_tokens: number;
  script: string;
  command: string[];
  environment: Record<string, string>;
  required_features: string[];
}

export interface RuntimeProfileValidation {
  name: string;
  runtime: string;
  status: 'ready' | 'missing';
  script_exists: boolean;
  package: string | null;
  package_version: string | null;
  executable: string | null;
  gpu_available: boolean;
  probe_command: string[];
  probe_status: 'passed' | 'failed' | 'skipped';
  probe_exit_code: number | null;
  probe_output: string | null;
  detail: string;
}

export interface RuntimeProfileReport {
  status: 'ready' | 'incomplete';
  created_at: string;
  profiles: RuntimeLaunchProfile[];
  validations: RuntimeProfileValidation[];
}

export interface ForgetReport {
  source_id: string;
  atom_ids: string[];
  atoms_deleted: number;
  edges_deleted: number;
  cache_entries_cleared: number;
  semantic_cache_cleared: number;
  vectors_dropped: number;
  visual_index_dropped: boolean;
  affected_cartridges: Array<Record<string, unknown>>;
  reason: string;
}
