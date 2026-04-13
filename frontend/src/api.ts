import {
  LiteratureSearchRecord,
  ReferenceAsset,
  RunResponse,
  SessionDetailResponse,
  SessionSummary,
} from "./types";

const API_BASE = "http://127.0.0.1:8000";

export async function listSessions(): Promise<SessionSummary[]> {
  const response = await fetch(`${API_BASE}/sessions`);
  const payload = await response.json();
  return payload.sessions;
}

export async function createSession(body: {
  session_name: string;
  categories: string[];
  user_goal?: string;
  background?: string;
}): Promise<SessionDetailResponse> {
  const response = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return response.json();
}

export async function getSession(sessionId: string): Promise<SessionDetailResponse> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
  return response.json();
}

export async function uploadPapers(sessionId: string, files: File[]): Promise<SessionDetailResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/papers`, {
    method: "POST",
    body: formData
  });
  return response.json();
}

export async function createRun(sessionId: string, body: {
  mode: "analyze" | "answer" | "archive";
  input: string;
  preferred_paper_ids: string[];
}): Promise<RunResponse> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  return response.json();
}

export function runEventsUrl(sessionId: string, runId: string): string {
  return `${API_BASE}/sessions/${sessionId}/runs/${runId}/events`;
}

export async function discoverLiterature(sessionId: string, body: {
  query: string;
  discovery_mode: "latest_top_venues" | "seminal" | "related";
  domain: "general" | "cs" | "biomed";
  max_results: number;
  preferred_venues: string[];
}): Promise<LiteratureSearchRecord> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/discover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const payload = await response.json();
  return payload.search;
}

export async function listDiscoveries(sessionId: string): Promise<LiteratureSearchRecord[]> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/discover`);
  const payload = await response.json();
  return payload.searches;
}

export async function localizeDiscoveryReference(sessionId: string, searchId: string, resultId: string): Promise<ReferenceAsset> {
  const response = await fetch(`${API_BASE}/sessions/${sessionId}/discover/${searchId}/localize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result_id: resultId })
  });
  const payload = await response.json();
  return payload.reference;
}
