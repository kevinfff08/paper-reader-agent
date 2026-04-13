export type SessionSummary = {
  session_id: string;
  session_name: string;
  session_slug: string;
  categories: string[];
  user_goal?: string | null;
  background?: string | null;
  external_links: string[];
  created_at: string;
  updated_at: string;
};

export type PaperAsset = {
  paper_id: string;
  filename: string;
  title?: string | null;
  original_path: string;
};

export type AnalysisSection = {
  key: string;
  title: string;
  content: string;
};

export type AnalysisArtifact = {
  analysis_id: string;
  title: string;
  paper_ids: string[];
  sections: AnalysisSection[];
  markdown_path: string;
  created_at: string;
};

export type EvidenceRef = {
  source_type?: "paper" | "analysis" | "reference";
  asset_id?: string;
  label: string;
  excerpt: string;
  locator?: string | null;
  source_kind?: string | null;
  source_url?: string | null;
  page_label?: string | null;
  score?: number | null;
};

export type ReferenceAsset = {
  reference_id: string;
  title: string;
  source_kind: string;
  source_url: string;
  summary: string;
  localized_path?: string | null;
  doi?: string | null;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  citation_count?: number | null;
  landing_page_url?: string | null;
  pdf_url?: string | null;
  best_access_url?: string | null;
  manual_search_url?: string | null;
  oa_status?: string;
  acquisition_status?: string;
  search_reason?: string | null;
  is_supplementary?: boolean;
};

export type QARecord = {
  question_id: string;
  question_text: string;
  answer_text: string;
  evidence_refs: EvidenceRef[];
  retrieval_refs: ReferenceAsset[];
  verification_status:
    | "not_needed"
    | "verified_uploaded_paper"
    | "verified_session_local"
    | "supplemented_external"
    | "links_only"
    | "unverified";
  created_at: string;
};

export type MemoryNote = {
  session_id?: string;
  path?: string;
  confirmed_points: string[];
  unresolved_points: string[];
  tracked_questions: string[];
  paper_titles: string[];
  reference_titles: string[];
  updated_at?: string;
};

export type ArchiveArtifact = {
  archive_id: string;
  session_id?: string;
  markdown_path: string;
  created_at: string;
};

export type EvidenceLedgerEntry = {
  evidence_id: string;
  session_id: string;
  run_id?: string | null;
  source_type: "paper" | "analysis" | "reference";
  asset_id: string;
  label: string;
  excerpt: string;
  locator?: string | null;
  recorded_at: string;
};

export type CompactSummary = {
  summary_id: string;
  session_id: string;
  boundary_label: string;
  content: string;
  boundary_id?: string | null;
  snapshot_version?: number | null;
  preserved_tail_anchor?: string | null;
  restored_context_refs: string[];
  created_at: string;
};

export type LibraryCard = {
  card_id: string;
  session_id: string;
  card_type: "paper" | "concept" | "session";
  title: string;
  content: string;
  linked_asset_ids: string[];
  created_at: string;
};

export type RunSummary = {
  run_id: string;
  session_id: string;
  mode: "analyze" | "answer" | "archive";
  status: "pending" | "running" | "completed" | "failed";
  input_text: string;
  preferred_paper_ids: string[];
  risk_level?: "low" | "medium" | "high" | null;
  working_state_version: number;
  active_background_task_ids: string[];
  verification_state?: "not_requested" | "pending" | "passed" | "failed" | null;
  final_artifact_ref?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type RunEvent = {
  event_id: string;
  run_id: string;
  sequence_number: number;
  event_type:
    | "run_started"
    | "assistant_delta"
    | "tool_call_started"
    | "tool_call_finished"
    | "evidence_added"
    | "verification_required"
    | "memory_updated"
    | "run_completed"
    | "run_failed";
  payload: Record<string, unknown>;
  created_at: string;
};

export type TaskSummary = {
  task_id: string;
  session_id: string;
  agent_kind: "compact" | "session_memory_update" | "memory_extraction" | "verification";
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  parent_run_id?: string | null;
  input_text: string;
  snapshot_version?: number | null;
  progress: number;
  current_step?: string | null;
  output_preview?: string | null;
  result_payload: Record<string, unknown>;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type TaskEvent = {
  event_id: string;
  task_id: string;
  sequence_number: number;
  event_type:
    | "task_started"
    | "task_progress"
    | "task_log"
    | "task_output"
    | "task_completed"
    | "task_failed"
    | "task_cancelled";
  payload: Record<string, unknown>;
  created_at: string;
};

export type VerificationNote = {
  verification_id: string;
  session_id: string;
  run_id?: string | null;
  question_text: string;
  status: "not_requested" | "pending" | "passed" | "failed";
  rationale: string;
  evidence_labels: string[];
  created_at: string;
};

export type SessionFileEntry = {
  file_id: string;
  label: string;
  path: string;
  category: "paper" | "parsed" | "reference" | "analysis" | "archive" | "memory" | "task";
  updated_at?: string | null;
};

export type SessionArtifacts = {
  papers: PaperAsset[];
  references: ReferenceAsset[];
  analyses: AnalysisArtifact[];
  qa_records: QARecord[];
  memory?: MemoryNote | null;
  evidence_ledger: EvidenceLedgerEntry[];
  compact_summaries: CompactSummary[];
  library_cards: LibraryCard[];
  verification_memory: VerificationNote[];
  literature_searches: LiteratureSearchRecord[];
  runs: RunSummary[];
  tasks: TaskSummary[];
  session_files: SessionFileEntry[];
  archive?: ArchiveArtifact | null;
};

export type SessionDetailResponse = {
  session: SessionSummary;
  artifacts: SessionArtifacts;
};

export type RunResponse = {
  run: RunSummary;
};

export type TaskResponse = {
  task: TaskSummary;
};

export type DiscoveredPaper = {
  result_id: string;
  title: string;
  authors: string[];
  year?: number | null;
  venue?: string | null;
  source_kind: string;
  source_url: string;
  doi?: string | null;
  citation_count?: number | null;
  summary: string;
  landing_page_url?: string | null;
  pdf_url?: string | null;
  best_access_url?: string | null;
  manual_search_url?: string | null;
  oa_status?: string;
  acquisition_status?: string;
  search_reason?: string | null;
  is_supplementary?: boolean;
};

export type LiteratureSearchRecord = {
  search_id: string;
  session_id: string;
  query: string;
  discovery_mode: "latest_top_venues" | "seminal" | "related" | "supporting_context";
  domain: "general" | "cs" | "biomed";
  preferred_venues: string[];
  results: DiscoveredPaper[];
  created_at: string;
};
