import { FormEvent, useEffect, useState } from "react";
import {
  askQuestion,
  analyzeSession,
  buildArchive,
  createSession,
  getSession,
  listSessions,
  uploadPapers
} from "./api";
import { AnalysisArtifact, QARecord, SessionDetailResponse, SessionSummary } from "./types";

function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSession, setSelectedSession] = useState<SessionDetailResponse | null>(null);
  const [sessionName, setSessionName] = useState("");
  const [categories, setCategories] = useState("");
  const [focusQuestion, setFocusQuestion] = useState("");
  const [question, setQuestion] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);

  async function refreshSessions(sessionId?: string) {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
    const targetId = sessionId ?? selectedSession?.session.session_id;
    if (targetId) {
      const detail = await getSession(targetId);
      setSelectedSession(detail);
    } else if (nextSessions.length > 0) {
      const detail = await getSession(nextSessions[0].session_id);
      setSelectedSession(detail);
    }
  }

  useEffect(() => {
    void refreshSessions();
  }, []);

  async function onCreateSession(event: FormEvent) {
    event.preventDefault();
    if (!sessionName.trim()) {
      return;
    }
    setLoading(true);
    try {
      const detail = await createSession({
        session_name: sessionName.trim(),
        categories: categories.split(",").map((item) => item.trim()).filter(Boolean)
      });
      setSessionName("");
      setCategories("");
      setSelectedSession(detail);
      await refreshSessions(detail.session.session_id);
    } finally {
      setLoading(false);
    }
  }

  async function onUpload() {
    if (!selectedSession || uploadFiles.length === 0) {
      return;
    }
    setLoading(true);
    try {
      await uploadPapers(selectedSession.session.session_id, uploadFiles);
      setUploadFiles([]);
      await refreshSessions(selectedSession.session.session_id);
    } finally {
      setLoading(false);
    }
  }

  async function onAnalyze() {
    if (!selectedSession) {
      return;
    }
    setLoading(true);
    try {
      await analyzeSession(selectedSession.session.session_id, focusQuestion);
      await refreshSessions(selectedSession.session.session_id);
    } finally {
      setLoading(false);
    }
  }

  async function onAskQuestion(event: FormEvent) {
    event.preventDefault();
    if (!selectedSession || !question.trim()) {
      return;
    }
    setLoading(true);
    try {
      await askQuestion(selectedSession.session.session_id, question.trim());
      setQuestion("");
      await refreshSessions(selectedSession.session.session_id);
    } finally {
      setLoading(false);
    }
  }

  async function onArchive() {
    if (!selectedSession) {
      return;
    }
    setLoading(true);
    try {
      await buildArchive(selectedSession.session.session_id);
      await refreshSessions(selectedSession.session.session_id);
    } finally {
      setLoading(false);
    }
  }

  const latestAnalysis: AnalysisArtifact | undefined = selectedSession?.artifacts.analyses.at(-1);
  const qaRecords: QARecord[] = selectedSession?.artifacts.qa_records ?? [];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <p className="eyebrow">PaperReader</p>
          <h1>Study Sessions</h1>
        </div>
        <form className="panel" onSubmit={onCreateSession}>
          <h2>Create Session</h2>
          <input
            placeholder="Session name"
            value={sessionName}
            onChange={(event) => setSessionName(event.target.value)}
          />
          <input
            placeholder="Categories (comma separated)"
            value={categories}
            onChange={(event) => setCategories(event.target.value)}
          />
          <button type="submit" disabled={loading}>Create</button>
        </form>
        <div className="panel session-list">
          {sessions.map((session) => (
            <button
              key={session.session_id}
              className={`session-item ${selectedSession?.session.session_id === session.session_id ? "active" : ""}`}
              onClick={() => void refreshSessions(session.session_id)}
            >
              <span>{session.session_name}</span>
              <small>{session.categories.join(", ") || "Uncategorized"}</small>
            </button>
          ))}
        </div>
      </aside>

      <main className="workspace">
        {!selectedSession ? (
          <div className="empty-state">
            <h2>No session selected</h2>
            <p>Create a session to start reading papers.</p>
          </div>
        ) : (
          <>
            <header className="workspace-header">
              <div>
                <p className="eyebrow">Session</p>
                <h2>{selectedSession.session.session_name}</h2>
                <p className="subtle">
                  {selectedSession.session.categories.join(", ") || "Uncategorized"}
                </p>
              </div>
              <button className="archive-button" onClick={() => void onArchive()} disabled={loading}>
                Generate Archive
              </button>
            </header>

            <section className="workspace-grid">
              <div className="panel column">
                <h3>Papers & Sources</h3>
                <input
                  type="file"
                  multiple
                  onChange={(event) => setUploadFiles(Array.from(event.target.files ?? []))}
                />
                <button onClick={() => void onUpload()} disabled={loading || uploadFiles.length === 0}>
                  Upload Papers
                </button>
                <ul className="plain-list">
                  {selectedSession.artifacts.papers.map((paper) => (
                    <li key={paper.paper_id}>
                      <strong>{paper.title || paper.filename}</strong>
                      <div className="subtle">{paper.filename}</div>
                    </li>
                  ))}
                </ul>
                <div className="divider" />
                <h4>Localized References</h4>
                <ul className="plain-list">
                  {selectedSession.artifacts.references.map((reference) => (
                    <li key={reference.reference_id}>
                      <strong>{reference.title}</strong>
                      <div className="subtle">{reference.source_kind}</div>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="panel column analysis-column">
                <div className="analysis-actions">
                  <input
                    placeholder="Optional focus question"
                    value={focusQuestion}
                    onChange={(event) => setFocusQuestion(event.target.value)}
                  />
                  <button onClick={() => void onAnalyze()} disabled={loading || selectedSession.artifacts.papers.length === 0}>
                    Analyze Session
                  </button>
                </div>
                <h3>Initial Analysis</h3>
                {latestAnalysis ? (
                  latestAnalysis.sections.map((section) => (
                    <article key={section.key} className="analysis-section">
                      <h4>{section.title}</h4>
                      <p>{section.content}</p>
                    </article>
                  ))
                ) : (
                  <p className="subtle">Upload papers and run analysis to populate this workspace.</p>
                )}
              </div>

              <div className="panel column">
                <h3>Q&A Workspace</h3>
                <form onSubmit={onAskQuestion} className="qa-form">
                  <textarea
                    placeholder="Ask a follow-up question"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                  />
                  <button type="submit" disabled={loading || !question.trim()}>
                    Ask
                  </button>
                </form>
                <div className="qa-list">
                  {qaRecords.map((record) => (
                    <article key={record.question_id} className="qa-card">
                      <h4>{record.question_text}</h4>
                      <p>{record.answer_text}</p>
                      <div className="meta-block">
                        <span>Verification: {record.verification_status}</span>
                        <span>Evidence: {record.evidence_refs.length}</span>
                        <span>New refs: {record.retrieval_refs.length}</span>
                      </div>
                    </article>
                  ))}
                </div>
                {selectedSession.artifacts.archive?.markdown_path && (
                  <div className="archive-path">
                    Archive ready: <code>{selectedSession.artifacts.archive.markdown_path}</code>
                  </div>
                )}
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
