export type TaskStatus = {
  task_id: string;
  phase: string;
  state: string;
  message: string;
  created_at: string;
  updated_at: string;
};

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
  latest_task?: TaskStatus | null;
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
  label: string;
  excerpt: string;
  locator?: string | null;
};

export type ReferenceAsset = {
  reference_id: string;
  title: string;
  source_kind: string;
  source_url: string;
  summary: string;
};

export type QARecord = {
  question_id: string;
  question_text: string;
  answer_text: string;
  evidence_refs: EvidenceRef[];
  retrieval_refs: ReferenceAsset[];
  verification_status: string;
  created_at: string;
};

export type MemoryNote = {
  confirmed_points: string[];
  unresolved_points: string[];
  tracked_questions: string[];
  paper_titles: string[];
  reference_titles: string[];
};

export type ArchiveArtifact = {
  archive_id: string;
  markdown_path: string;
  created_at: string;
};

export type SessionArtifacts = {
  papers: PaperAsset[];
  references: ReferenceAsset[];
  analyses: AnalysisArtifact[];
  qa_records: QARecord[];
  memory?: MemoryNote | null;
  archive?: ArchiveArtifact | null;
};

export type SessionDetailResponse = {
  session: SessionSummary;
  artifacts: SessionArtifacts;
};
