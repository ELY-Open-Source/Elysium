package domain

// Memory mirrors the Evidence Atom the Ely-Eye API returns for a write. The
// server stamps holder, origin and ingestion time, so the MCP side never
// invents them.
type Memory struct {
	AtomID             string   `json:"atom_id"`
	SourceID           string   `json:"source_id"`
	Source             string   `json:"source"`
	HolderID           string   `json:"holder_id"`
	Origin             string   `json:"origin"`
	Scenario           string   `json:"scenario"`
	SessionID          string   `json:"session_id,omitempty"`
	Text               string   `json:"text"`
	IngestedAt         string   `json:"ingested_at"`
	EventTime          string   `json:"event_time,omitempty"`
	EventTimePrecision string   `json:"event_time_precision,omitempty"`
	ValidFrom          string   `json:"valid_from,omitempty"`
	ValidTo            string   `json:"valid_to,omitempty"`
	RetentionUntil     string   `json:"retention_until,omitempty"`
	Supersedes         []string `json:"supersedes"`
	TokenEquivalent    int64    `json:"token_equivalent"`
	// RecallCount is what the store observed: how many searches handed this memory
	// back. A caller cannot set it, which is why an archive rule can trust it.
	RecallCount    int      `json:"recall_count"`
	Importance     *float64 `json:"importance,omitempty"`
	LastRecalledAt string   `json:"last_recalled_at,omitempty"`
}

// ConflictRecord is one disagreement the store noticed between two of a holder's
// memories and nobody has settled. While it stands the store drops the older side
// from a page; settling it stays the holder's decision.
type ConflictRecord struct {
	ConflictID  int      `json:"conflict_id"`
	OlderAtomID string   `json:"older_atom_id"`
	NewerAtomID string   `json:"newer_atom_id"`
	HolderID    string   `json:"holder_id"`
	Scenario    string   `json:"scenario"`
	Terms       []string `json:"terms"`
	OlderValue  string   `json:"older_value"`
	NewerValue  string   `json:"newer_value"`
	DetectedAt  string   `json:"detected_at"`
	ResolvedAt  string   `json:"resolved_at,omitempty"`
}

type ForgetReport struct {
	SourceID            string   `json:"source_id"`
	AtomIDs             []string `json:"atom_ids"`
	AtomsDeleted        int      `json:"atoms_deleted"`
	EdgesDeleted        int      `json:"edges_deleted"`
	CacheEntriesCleared int      `json:"cache_entries_cleared"`
	// SemanticCacheCleared counts compiled contexts deleted by the same forget.
	SemanticCacheCleared int    `json:"semantic_cache_cleared"`
	VectorsDropped       int    `json:"vectors_dropped"`
	VisualIndexDropped   bool   `json:"visual_index_dropped"`
	AffectedCartridges   []any  `json:"affected_cartridges"`
	Reason               string `json:"reason"`
}

type CacheLayer struct {
	Layer         string `json:"layer"`
	Entries       int    `json:"entries"`
	BytesEstimate int64  `json:"bytes_estimate"`
	HitCount      int    `json:"hit_count"`
	MissCount     int    `json:"miss_count"`
	LastEventAt   string `json:"last_event_at,omitempty"`
}

type Status struct {
	App                    string       `json:"app"`
	ProjectRoot            string       `json:"project_root"`
	DataHome               string       `json:"data_home"`
	Database               string       `json:"database"`
	AtomCount              int          `json:"atom_count"`
	SourceCount            int          `json:"source_count"`
	CartridgeCount         int          `json:"cartridge_count"`
	ActiveTokenEquivalent  int64        `json:"active_token_equivalent"`
	LibraryTokenEquivalent int64        `json:"library_token_equivalent"`
	CacheLayers            []CacheLayer `json:"cache_layers"`
}

type Cartridge struct {
	CartridgeID     string `json:"cartridge_id"`
	Name            string `json:"name"`
	RootPath        string `json:"root_path"`
	DNA             string `json:"dna,omitempty"`
	TokenEquivalent int64  `json:"token_equivalent"`
	CreatedAt       string `json:"created_at"`
	Manifest        any    `json:"manifest,omitempty"`
}

type CartridgeDetail struct {
	Cartridge
	Artifacts          map[string]string `json:"artifacts"`
	MemoryCapsuleIndex any               `json:"memory_capsule_index,omitempty"`
	AssetReport        any               `json:"asset_report,omitempty"`
}

// MountState is what the server lets a search see right now.
type MountState struct {
	Mounted      []string `json:"mounted"`
	Scoped       bool     `json:"scoped"`
	AtomsInScope int      `json:"atoms_in_scope"`
}

// CartridgeManifest is the header a cartridge carries, including the KV fingerprint
// that decides whether it may be mounted on this machine.
type CartridgeManifest struct {
	CartridgeID     string            `json:"cartridge_id"`
	Name            string            `json:"name"`
	CreatedAt       string            `json:"created_at"`
	ModelBase       string            `json:"model_base"`
	SourceCount     int               `json:"source_count"`
	AtomCount       int               `json:"atom_count"`
	TokenEquivalent int64             `json:"token_equivalent"`
	Artifacts       map[string]string `json:"artifacts"`
	KVFingerprint   map[string]any    `json:"kv_fingerprint,omitempty"`
	DNA             string            `json:"dna,omitempty"`
}

type Atom struct {
	AtomID          string `json:"atom_id"`
	SourceID        string `json:"source_id"`
	Modality        string `json:"modality"`
	Source          string `json:"source"`
	IngestedAt      string `json:"ingested_at"`
	HolderID        string `json:"holder_id,omitempty"`
	Origin          string `json:"origin,omitempty"`
	Scenario        string `json:"scenario,omitempty"`
	EventTime       string `json:"event_time,omitempty"`
	Text            string `json:"text"`
	ImageRef        string `json:"image_ref,omitempty"`
	Layout          any    `json:"layout,omitempty"`
	Relations       any    `json:"relations,omitempty"`
	Trust           any    `json:"trust,omitempty"`
	TokenEquivalent int64  `json:"token_equivalent"`
	Metadata        any    `json:"metadata,omitempty"`
}

type AtomHit struct {
	Atom        Atom    `json:"atom"`
	SparseScore float64 `json:"sparse_score"`
	DenseScore  float64 `json:"dense_score"`
	FinalScore  float64 `json:"final_score"`
}

type AtomSummary struct {
	AtomID          string `json:"atom_id"`
	SourceID        string `json:"source_id"`
	Modality        string `json:"modality"`
	Source          string `json:"source"`
	IngestedAt      string `json:"ingested_at"`
	HolderID        string `json:"holder_id,omitempty"`
	Scenario        string `json:"scenario,omitempty"`
	TextPreview     string `json:"text_preview"`
	ImageRef        string `json:"image_ref,omitempty"`
	TokenEquivalent int64  `json:"token_equivalent"`
}

type AtomSearchHit struct {
	Atom        AtomSummary `json:"atom"`
	SparseScore float64     `json:"sparse_score"`
	FinalScore  float64     `json:"final_score"`
}

type EvidencePack struct {
	Question         string          `json:"question"`
	Profile          string          `json:"profile"`
	TokenBudget      int64           `json:"token_budget"`
	TokenEquivalent  int64           `json:"token_equivalent"`
	CacheTraceID     string          `json:"cache_trace_id"`
	Hits             []AtomSearchHit `json:"hits"`
	PackedText       string          `json:"packed_text"`
	VerifierContract []string        `json:"verifier_contract"`
}

type ProofSuite struct {
	ProofID     string `json:"proof_id"`
	CartridgeID string `json:"cartridge_id"`
	Status      string `json:"status"`
	CreatedAt   string `json:"created_at"`
	Path        string `json:"path"`
	Payload     any    `json:"payload,omitempty"`
}

type HashHopProof struct {
	ProofID          string   `json:"proof_id"`
	Kind             string   `json:"kind"`
	Hops             int      `json:"hops"`
	TokenEquivalent  int64    `json:"token_equivalent"`
	QueryID          string   `json:"query_id"`
	ExpectedTargetID string   `json:"expected_target_id"`
	ModelTargetID    string   `json:"model_target_id,omitempty"`
	Passed           *bool    `json:"passed"`
	Artifacts        []string `json:"artifacts,omitempty"`
	CreatedAt        string   `json:"created_at"`
	Path             string   `json:"path"`
}

type HashHopBucket struct {
	Kind            string `json:"kind"`
	Hops            int    `json:"hops"`
	TokenEquivalent int64  `json:"token_equivalent"`
	Total           int    `json:"total"`
	Passed          int    `json:"passed"`
}

type HashHopReport struct {
	Total   int             `json:"total"`
	Passed  int             `json:"passed"`
	Buckets []HashHopBucket `json:"buckets"`
	Proofs  []HashHopProof  `json:"proofs,omitempty"`
}

type ProofCheck struct {
	Name        string   `json:"name"`
	Requirement string   `json:"requirement"`
	Status      string   `json:"status"`
	Evidence    []string `json:"evidence,omitempty"`
	Detail      string   `json:"detail"`
}

type ProofSuiteDetail struct {
	ProofID     string            `json:"proof_id"`
	CartridgeID string            `json:"cartridge_id"`
	Status      string            `json:"status"`
	CreatedAt   string            `json:"created_at"`
	Checks      []ProofCheck      `json:"checks"`
	Artifacts   map[string]string `json:"artifacts"`
	DNABefore   string            `json:"dna_before,omitempty"`
	DNAAfter    string            `json:"dna_after,omitempty"`
	Path        string            `json:"path"`
	HashHop     HashHopReport     `json:"hashhop"`
}

type Holder struct {
	HolderID   string            `json:"holder_id"`
	Name       string            `json:"name"`
	Kind       string            `json:"kind"`
	KnowsAbout []string          `json:"knows_about"`
	Contact    map[string]string `json:"contact"`
	CreatedAt  string            `json:"created_at"`
	UpdatedAt  string            `json:"updated_at"`
}

type WhoKnowsHit struct {
	HolderID   string            `json:"holder_id"`
	Name       string            `json:"name"`
	Confidence float64           `json:"confidence"`
	Matched    int64             `json:"matched"`
	TopScore   float64           `json:"top_score"`
	LatestTime string            `json:"latest_time,omitempty"`
	Basis      []string          `json:"basis"`
	Contact    map[string]string `json:"contact"`
}

type WhoKnowsReport struct {
	Query    string        `json:"query"`
	AsHolder string        `json:"as_holder,omitempty"`
	Status   string        `json:"status"`
	Hits     []WhoKnowsHit `json:"hits"`
}

type ReferralAnswer struct {
	Question   string   `json:"question"`
	AsHolder   string   `json:"as_holder,omitempty"`
	Status     string   `json:"status"`
	AnsweredBy string   `json:"answered_by,omitempty"`
	Asked      []string `json:"asked"`
	Hops       int64    `json:"hops"`
	AtomIDs    []string `json:"atom_ids"`
	Answer     string   `json:"answer,omitempty"`
	Basis      []string `json:"basis"`
}
