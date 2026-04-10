import { SessionDetailResponse, SessionSummary } from "./types";

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

export async function analyzeSession(sessionId: string, focusQuestion: string): Promise<void> {
  await fetch(`${API_BASE}/sessions/${sessionId}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ focus_question: focusQuestion || null })
  });
}

export async function askQuestion(sessionId: string, question: string): Promise<void> {
  await fetch(`${API_BASE}/sessions/${sessionId}/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, preferred_paper_ids: [] })
  });
}

export async function buildArchive(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/sessions/${sessionId}/archive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_qa: true })
  });
}
