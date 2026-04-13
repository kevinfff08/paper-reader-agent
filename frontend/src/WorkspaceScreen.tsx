import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  createRun,
  createSession,
  discoverLiterature,
  getSession,
  listSessions,
  localizeDiscoveryReference,
  runEventsUrl,
  uploadPapers
} from "./api";
import {
  AnalysisArtifact,
  LiteratureSearchRecord,
  QARecord,
  ReferenceAsset,
  RunEvent,
  RunSummary,
  SessionDetailResponse,
  SessionSummary
} from "./types";


function formatRunEvent(event: RunEvent): string {
  switch (event.event_type) {
    case "run_started":
      return `Started ${String(event.payload.mode ?? "run")} mode`;
    case "tool_call_started":
      return `Running ${String(event.payload.tool ?? "tool")}`;
    case "tool_call_finished":
      return `Finished ${String(event.payload.tool ?? "tool")}`;
    case "evidence_added":
      return `Added evidence: ${String(event.payload.label ?? "evidence")}`;
    case "verification_required":
      return `Verification: ${JSON.stringify(event.payload)}`;
    case "memory_updated":
      return "Session memory updated";
    case "run_completed":
      return "Run completed";
    case "run_failed":
      return `Run failed: ${String(event.payload.error ?? "unknown error")}`;
    case "assistant_delta":
      return "Streaming answer chunk";
    default:
      return event.event_type;
  }
}

function getPrimaryAccessUrl(reference: Pick<ReferenceAsset, "best_access_url" | "landing_page_url" | "source_url">): string | null {
  return reference.best_access_url ?? reference.landing_page_url ?? reference.source_url ?? null;
}

function WorkspaceScreen() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSession, setSelectedSession] = useState<SessionDetailResponse | null>(null);
  const [sessionName, setSessionName] = useState("");
  const [categories, setCategories] = useState("");
  const [focusQuestion, setFocusQuestion] = useState("");
  const [question, setQuestion] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeRun, setActiveRun] = useState<RunSummary | null>(null);
  const [runEvents, setRunEvents] = useState<RunEvent[]>([]);
  const [streamedText, setStreamedText] = useState("");
  const [discoveryQuery, setDiscoveryQuery] = useState("");
  const [discoveryMode, setDiscoveryMode] = useState<"latest_top_venues" | "seminal" | "related">("latest_top_venues");
  const [discoveryDomain, setDiscoveryDomain] = useState<"general" | "cs" | "biomed">("general");
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [currentSearch, setCurrentSearch] = useState<LiteratureSearchRecord | null>(null);
  const [localizingResultId, setLocalizingResultId] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  async function refreshSessions(sessionId?: string) {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
    const targetId = sessionId ?? selectedSession?.session.session_id;
    if (targetId) {
      const detail = await getSession(targetId);
      setSelectedSession(detail);
      if (!currentSearch && detail.artifacts.literature_searches.length > 0) {
        setCurrentSearch(detail.artifacts.literature_searches[detail.artifacts.literature_searches.length - 1] ?? null);
      }
    } else if (nextSessions.length > 0) {
      const detail = await getSession(nextSessions[0].session_id);
      setSelectedSession(detail);
      if (detail.artifacts.literature_searches.length > 0) {
        setCurrentSearch(detail.artifacts.literature_searches[detail.artifacts.literature_searches.length - 1] ?? null);
      }
    }
  }

  useEffect(() => {
    void refreshSessions();
  }, []);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
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
      setCurrentSearch(detail.artifacts.literature_searches[detail.artifacts.literature_searches.length - 1] ?? null);
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

  async function startStreamingRun(mode: "analyze" | "answer" | "archive", input: string) {
    if (!selectedSession) {
      return;
    }
    eventSourceRef.current?.close();
    setLoading(true);
    setStreamedText("");
    setRunEvents([]);
    try {
      const response = await createRun(selectedSession.session.session_id, {
        mode,
        input,
        preferred_paper_ids: []
      });
      setActiveRun(response.run);

      const source = new EventSource(runEventsUrl(selectedSession.session.session_id, response.run.run_id));
      eventSourceRef.current = source;
      source.onmessage = (message) => {
        const event: RunEvent = JSON.parse(message.data);
        setRunEvents((current) => [...current, event]);
        if (event.event_type === "run_started") {
          setActiveRun((current) => current ? { ...current, status: "running" } : current);
        }
        if (event.event_type === "assistant_delta") {
          const delta = String(event.payload.delta ?? "");
          setStreamedText((current) => current + delta);
        }
        if (event.event_type === "run_completed" || event.event_type === "run_failed") {
          source.close();
          eventSourceRef.current = null;
          void refreshSessions(selectedSession.session.session_id);
          setLoading(false);
          setActiveRun((current) =>
            current ? { ...current, status: event.event_type === "run_completed" ? "completed" : "failed" } : current
          );
        }
      };
      source.onerror = () => {
        source.close();
        eventSourceRef.current = null;
        void refreshSessions(selectedSession.session.session_id);
        setLoading(false);
      };
    } catch (error) {
      setLoading(false);
      throw error;
    }
  }

  async function onAnalyze() {
    if (!selectedSession) {
      return;
    }
    await startStreamingRun("analyze", focusQuestion.trim());
  }

  async function onAskQuestion(event: FormEvent) {
    event.preventDefault();
    if (!selectedSession || !question.trim()) {
      return;
    }
    const nextQuestion = question.trim();
    setQuestion("");
    await startStreamingRun("answer", nextQuestion);
  }

  async function onArchive() {
    if (!selectedSession) {
      return;
    }
    await startStreamingRun("archive", "build archive");
  }

  async function onDiscover(event: FormEvent) {
    event.preventDefault();
    if (!selectedSession || !discoveryQuery.trim()) {
      return;
    }
    setDiscoveryLoading(true);
    try {
      const search = await discoverLiterature(selectedSession.session.session_id, {
        query: discoveryQuery.trim(),
        discovery_mode: discoveryMode,
        domain: discoveryDomain,
        max_results: 10,
        preferred_venues: []
      });
      setCurrentSearch(search);
      await refreshSessions(selectedSession.session.session_id);
    } finally {
      setDiscoveryLoading(false);
    }
  }

  async function onLocalizeResult(resultId: string) {
    if (!selectedSession || !currentSearch) {
      return;
    }
    setLocalizingResultId(resultId);
    try {
      await localizeDiscoveryReference(selectedSession.session.session_id, currentSearch.search_id, resultId);
      await refreshSessions(selectedSession.session.session_id);
    } finally {
      setLocalizingResultId(null);
    }
  }

  const analyses = selectedSession?.artifacts.analyses ?? [];
  const runs = selectedSession?.artifacts.runs ?? [];
  const latestAnalysis: AnalysisArtifact | undefined = analyses[analyses.length - 1];
  const qaRecords: QARecord[] = selectedSession?.artifacts.qa_records ?? [];
  const latestRunStatus = activeRun?.status ?? runs[runs.length - 1]?.status ?? null;
  const streamedEventLog = runEvents.slice(-8);
  const discoveryHistory = selectedSession?.artifacts.literature_searches ?? [];
  const currentResults = currentSearch?.results ?? [];
  const referenceIds = useMemo(
    () => new Set(selectedSession?.artifacts.references.map((reference) => reference.title.toLowerCase()) ?? []),
    [selectedSession]
  );

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

            {(activeRun || streamedEventLog.length > 0) && (
              <section className="panel run-panel">
                <div className="run-panel-header">
                  <div>
                    <p className="eyebrow">Active Runtime</p>
                    <h3>{activeRun?.mode ?? "recent"} run</h3>
                  </div>
                  <span className={`status-chip status-${latestRunStatus ?? "idle"}`}>
                    {latestRunStatus ?? "idle"}
                  </span>
                </div>
                {streamedText && (
                  <div className="stream-preview">
                    <pre>{streamedText}</pre>
                  </div>
                )}
                <div className="event-list">
                  {streamedEventLog.map((event) => (
                    <div key={event.event_id} className="event-item">
                      <strong>{event.event_type}</strong>
                      <span>{formatRunEvent(event)}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

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
                <h4>Find Papers</h4>
                <form className="discovery-form" onSubmit={onDiscover}>
                  <input
                    placeholder="Search papers, venues, or topics"
                    value={discoveryQuery}
                    onChange={(event) => setDiscoveryQuery(event.target.value)}
                  />
                  <div className="inline-controls">
                    <select value={discoveryMode} onChange={(event) => setDiscoveryMode(event.target.value as typeof discoveryMode)}>
                      <option value="latest_top_venues">Latest</option>
                      <option value="seminal">Seminal</option>
                      <option value="related">Related</option>
                    </select>
                    <select value={discoveryDomain} onChange={(event) => setDiscoveryDomain(event.target.value as typeof discoveryDomain)}>
                      <option value="general">General</option>
                      <option value="cs">CS</option>
                      <option value="biomed">Biomed</option>
                    </select>
                  </div>
                  <button type="submit" disabled={discoveryLoading || !discoveryQuery.trim()}>
                    {discoveryLoading ? "Searching..." : "Search"}
                  </button>
                </form>
                {discoveryHistory.length > 0 && (
                  <div className="history-strip">
                    {discoveryHistory.slice(-3).reverse().map((search) => (
                      <button key={search.search_id} className="history-chip" onClick={() => setCurrentSearch(search)}>
                        {search.query}
                      </button>
                    ))}
                  </div>
                )}
                {currentSearch && (
                  <div className="discovery-results">
                    {currentResults.map((result) => (
                      <article key={result.result_id} className="discovery-card">
                        <div className="discovery-card-header">
                          <strong>{result.title}</strong>
                          <span className="status-chip status-idle">{result.source_kind}</span>
                        </div>
                        <div className="meta-block">
                          <span>{result.venue || "Unknown venue"}</span>
                          <span>{result.year ?? "N/A"}</span>
                          <span>Citations: {result.citation_count ?? "N/A"}</span>
                          <span>Status: {result.acquisition_status ?? "metadata_only"}</span>
                        </div>
                        {result.summary && <p className="subtle">{result.summary}</p>}
                        <div className="link-row">
                          {result.landing_page_url && (
                            <a href={result.landing_page_url} target="_blank" rel="noreferrer">Open Landing</a>
                          )}
                          {result.pdf_url && (
                            <a href={result.pdf_url} target="_blank" rel="noreferrer">Open PDF</a>
                          )}
                          {result.manual_search_url && (
                            <a href={result.manual_search_url} target="_blank" rel="noreferrer">Search Web</a>
                          )}
                          <button
                            onClick={() => void onLocalizeResult(result.result_id)}
                            disabled={localizingResultId === result.result_id || referenceIds.has(result.title.toLowerCase())}
                          >
                            {referenceIds.has(result.title.toLowerCase()) ? "Localized" : (localizingResultId === result.result_id ? "Saving..." : "Localize Reference")}
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
                <div className="divider" />
                <h4>Localized References</h4>
                <ul className="plain-list">
                  {selectedSession.artifacts.references.map((reference) => {
                    const primaryAccessUrl = getPrimaryAccessUrl(reference);
                    return (
                      <li key={reference.reference_id}>
                        <strong>{reference.title}</strong>
                        <div className="subtle">
                          {reference.source_kind} | {reference.acquisition_status ?? "metadata_only"}
                          {reference.is_supplementary ? " | supplementary" : ""}
                        </div>
                        <div className="link-row">
                          {primaryAccessUrl && (
                            <a href={primaryAccessUrl} target="_blank" rel="noreferrer">Open</a>
                          )}
                          {reference.pdf_url && (
                            <a href={reference.pdf_url} target="_blank" rel="noreferrer">PDF</a>
                          )}
                          {reference.manual_search_url && (
                            <a href={reference.manual_search_url} target="_blank" rel="noreferrer">Search Web</a>
                          )}
                        </div>
                      </li>
                    );
                  })}
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
                {activeRun?.mode === "analyze" && streamedText ? (
                  <article className="analysis-section">
                    <h4>Streaming Analysis Draft</h4>
                    <p>{streamedText}</p>
                  </article>
                ) : latestAnalysis ? (
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
                  {activeRun?.mode === "answer" && streamedText && (
                    <article className="qa-card streaming-card">
                      <h4>Streaming Answer</h4>
                      <p>{streamedText}</p>
                    </article>
                  )}
                  {qaRecords.map((record) => (
                    <article key={record.question_id} className="qa-card">
                      <h4>{record.question_text}</h4>
                      <p>{record.answer_text}</p>
                      <div className="meta-block">
                        <span>Verification: {record.verification_status}</span>
                        <span>Evidence: {record.evidence_refs.length}</span>
                        <span>New refs: {record.retrieval_refs.length}</span>
                      </div>
                      {record.evidence_refs.length > 0 && (
                        <div className="evidence-block">
                          <strong>Evidence</strong>
                          <ul className="plain-list compact-list">
                            {record.evidence_refs.map((evidence, index) => (
                              <li key={`${record.question_id}-${index}`}>
                                <strong>{evidence.label}</strong>
                                <div className="subtle">{evidence.excerpt}</div>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {record.retrieval_refs.length > 0 && (
                        <div className="evidence-block">
                          <strong>Retrieved References</strong>
                          <ul className="plain-list compact-list">
                            {record.retrieval_refs.map((reference) => {
                              const primaryAccessUrl = getPrimaryAccessUrl(reference);
                              return (
                                <li key={reference.reference_id}>
                                  <strong>{reference.title}</strong>
                                  <div className="subtle">
                                    {reference.source_kind}
                                    {reference.is_supplementary ? " | supplementary" : ""}
                                  </div>
                                  <div className="link-row">
                                    {primaryAccessUrl && (
                                      <a href={primaryAccessUrl} target="_blank" rel="noreferrer">Open</a>
                                    )}
                                    {reference.pdf_url && (
                                      <a href={reference.pdf_url} target="_blank" rel="noreferrer">PDF</a>
                                    )}
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
                {selectedSession.artifacts.archive?.markdown_path && (
                  <div className="archive-path">
                    Archive ready: <code>{selectedSession.artifacts.archive.markdown_path}</code>
                  </div>
                )}
                {activeRun?.mode === "archive" && streamedText && (
                  <div className="archive-path">
                    <strong>Archive run output</strong>
                    <div>{streamedText}</div>
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

export default WorkspaceScreen;
