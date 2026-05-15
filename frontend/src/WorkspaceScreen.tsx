import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  createRun,
  createSession,
  discoverLiterature,
  getSession,
  listSessions,
  localizeDiscoveryReference,
  runEventsUrl,
  stopTask,
  taskEventsUrl,
  uploadPapers
} from "./api";
import type {
  AnalysisArtifact,
  LiteratureSearchRecord,
  QARecord,
  ReferenceAsset,
  RunEvent,
  RunSummary,
  SessionDetailResponse,
  SessionFileEntry,
  SessionSummary,
  TaskEvent,
  TaskSummary,
  VerificationNote
} from "./types";


function formatRunEvent(event: RunEvent): string {
  switch (event.event_type) {
    case "assistant_delta": {
      const delta = String(event.payload.delta ?? "").replace(/\s+/g, " ").trim();
      return delta ? `Delta: ${delta.slice(0, 180)}` : "Delta received";
    }
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
      return "Memory layer updated";
    case "run_completed":
      return "Run completed";
    case "run_failed":
      return `Run failed: ${String(event.payload.error ?? "unknown error")}`;
    default:
      return event.event_type;
  }
}

function formatTaskEvent(event: TaskEvent): string {
  if (event.event_type === "task_progress") {
    return `${String(event.payload.current_step ?? "progress")} (${String(event.payload.progress ?? 0)}%)`;
  }
  if (event.event_type === "task_log") {
    return String(event.payload.message ?? "Task log");
  }
  if (event.event_type === "task_output") {
    return String(event.payload.output_preview ?? "Task output ready");
  }
  return event.event_type;
}

function getPrimaryAccessUrl(reference: Pick<ReferenceAsset, "best_access_url" | "landing_page_url" | "source_url">): string | null {
  return reference.best_access_url ?? reference.landing_page_url ?? reference.source_url ?? null;
}

function isTaskTerminal(task: TaskSummary): boolean {
  return ["completed", "failed", "cancelled"].includes(task.status);
}

function mergeTask(tasks: TaskSummary[], nextTask: TaskSummary): TaskSummary[] {
  const others = tasks.filter((task) => task.task_id !== nextTask.task_id);
  return [nextTask, ...others].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

function updateArtifactsTask(detail: SessionDetailResponse | null, nextTask: TaskSummary): SessionDetailResponse | null {
  if (!detail) {
    return detail;
  }
  return {
    ...detail,
    artifacts: {
      ...detail.artifacts,
      tasks: mergeTask(detail.artifacts.tasks, nextTask),
    },
  };
}

function groupFiles(files: SessionFileEntry[]): Record<string, SessionFileEntry[]> {
  return files.reduce<Record<string, SessionFileEntry[]>>((acc, file) => {
    const key = file.category;
    acc[key] = [...(acc[key] ?? []), file];
    return acc;
  }, {});
}

export default function WorkspaceScreen() {
  const [view, setView] = useState<"workspace" | "sessions">("workspace");
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
  const [taskPanelOpen, setTaskPanelOpen] = useState(false);
  const [taskEvents, setTaskEvents] = useState<Record<string, TaskEvent[]>>({});
  const runSourceRef = useRef<EventSource | null>(null);
  const taskSourcesRef = useRef<Map<string, EventSource>>(new Map());

  async function refreshSessions(sessionId?: string) {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
    const targetId = sessionId ?? selectedSession?.session.session_id ?? nextSessions[0]?.session_id;
    if (!targetId) {
      return;
    }
    const detail = await getSession(targetId);
    setSelectedSession(detail);
    if (detail.artifacts.literature_searches.length > 0 && !currentSearch) {
      setCurrentSearch(detail.artifacts.literature_searches[detail.artifacts.literature_searches.length - 1] ?? null);
    }
    if (detail.artifacts.tasks.some((task) => !isTaskTerminal(task))) {
      setTaskPanelOpen(true);
    }
  }

  useEffect(() => {
    void refreshSessions();
  }, []);

  useEffect(() => {
    return () => {
      runSourceRef.current?.close();
      taskSourcesRef.current.forEach((source) => source.close());
      taskSourcesRef.current.clear();
    };
  }, []);

  useEffect(() => {
    const sessionId = selectedSession?.session.session_id;
    if (!sessionId) {
      return;
    }
    for (const task of selectedSession.artifacts.tasks) {
      if (isTaskTerminal(task) || taskSourcesRef.current.has(task.task_id)) {
        continue;
      }
      const source = new EventSource(taskEventsUrl(sessionId, task.task_id));
      taskSourcesRef.current.set(task.task_id, source);
      source.onmessage = (message) => {
        const event: TaskEvent = JSON.parse(message.data);
        setTaskEvents((current) => ({
          ...current,
          [task.task_id]: [...(current[task.task_id] ?? []), event].slice(-8),
        }));
        setSelectedSession((current) => {
          if (!current) {
            return current;
          }
          const existing = current.artifacts.tasks.find((item) => item.task_id === task.task_id);
          if (!existing) {
            return current;
          }
          let nextTask = existing;
          if (event.event_type === "task_progress") {
            nextTask = {
              ...existing,
              progress: Number(event.payload.progress ?? existing.progress),
              current_step: String(event.payload.current_step ?? existing.current_step ?? ""),
              status: "running",
              updated_at: event.created_at,
            };
          } else if (event.event_type === "task_output") {
            nextTask = {
              ...existing,
              output_preview: String(event.payload.output_preview ?? existing.output_preview ?? ""),
              updated_at: event.created_at,
            };
          } else if (event.event_type === "task_completed") {
            nextTask = { ...existing, status: "completed", progress: 100, updated_at: event.created_at };
          } else if (event.event_type === "task_failed") {
            nextTask = { ...existing, status: "failed", error_message: String(event.payload.error ?? ""), updated_at: event.created_at };
          } else if (event.event_type === "task_cancelled") {
            nextTask = { ...existing, status: "cancelled", updated_at: event.created_at };
          } else if (event.event_type === "task_started") {
            nextTask = { ...existing, status: "running", current_step: "starting", updated_at: event.created_at };
          }
          return updateArtifactsTask(current, nextTask);
        });
        setTaskPanelOpen(true);
        if (["task_completed", "task_failed", "task_cancelled"].includes(event.event_type)) {
          source.close();
          taskSourcesRef.current.delete(task.task_id);
          void refreshSessions(sessionId);
        }
      };
      source.onerror = () => {
        source.close();
        taskSourcesRef.current.delete(task.task_id);
      };
    }
  }, [selectedSession, currentSearch]);

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
      setCurrentSearch(null);
      setView("workspace");
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
    runSourceRef.current?.close();
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
      await refreshSessions(selectedSession.session.session_id);
      const source = new EventSource(runEventsUrl(selectedSession.session.session_id, response.run.run_id));
      runSourceRef.current = source;
      source.onmessage = (message) => {
        const event: RunEvent = JSON.parse(message.data);
        setRunEvents((current) => [...current, event].slice(-10));
        if (event.event_type === "run_started") {
          setActiveRun((current) => current ? { ...current, status: "running" } : current);
        }
        if (event.event_type === "assistant_delta") {
          const delta = String(event.payload.delta ?? "");
          setStreamedText((current) => current + delta);
        }
        if (event.event_type === "run_completed" || event.event_type === "run_failed") {
          source.close();
          runSourceRef.current = null;
          void refreshSessions(selectedSession.session.session_id);
          setLoading(false);
          setActiveRun((current) =>
            current ? { ...current, status: event.event_type === "run_completed" ? "completed" : "failed" } : current
          );
        }
      };
      source.onerror = () => {
        source.close();
        runSourceRef.current = null;
        setLoading(false);
      };
    } catch (error) {
      setLoading(false);
      throw error;
    }
  }

  async function onAnalyze() {
    await startStreamingRun("analyze", focusQuestion.trim());
  }

  async function onAskQuestion(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) {
      return;
    }
    const nextQuestion = question.trim();
    setQuestion("");
    await startStreamingRun("answer", nextQuestion);
  }

  async function onArchive() {
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

  async function onStopTask(taskId: string) {
    if (!selectedSession) {
      return;
    }
    const response = await stopTask(selectedSession.session.session_id, taskId);
    setSelectedSession((current) => updateArtifactsTask(current, response.task));
  }

  const analyses = selectedSession?.artifacts.analyses ?? [];
  const latestAnalysis: AnalysisArtifact | undefined = analyses[analyses.length - 1];
  const qaRecords: QARecord[] = selectedSession?.artifacts.qa_records ?? [];
  const latestRunStatus = activeRun?.status ?? selectedSession?.artifacts.runs[0]?.status ?? null;
  const discoveryHistory = selectedSession?.artifacts.literature_searches ?? [];
  const currentResults = currentSearch?.results ?? [];
  const referenceIds = useMemo(
    () => new Set(selectedSession?.artifacts.references.map((reference) => reference.title.toLowerCase()) ?? []),
    [selectedSession]
  );
  const filesByCategory = useMemo(
    () => groupFiles(selectedSession?.artifacts.session_files ?? []),
    [selectedSession]
  );
  const visibleTasks = selectedSession?.artifacts.tasks ?? [];
  const latestVerification: VerificationNote | undefined = selectedSession?.artifacts.verification_memory[0];

  if (view === "sessions") {
    return (
      <div className="session-manager">
        <header className="session-manager-header">
          <div>
            <p className="eyebrow">PaperReader</p>
            <h1>All Sessions</h1>
          </div>
          <button onClick={() => setView("workspace")} disabled={!selectedSession}>Open Workspace</button>
        </header>
        <div className="session-manager-grid">
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
          <section className="panel">
            <h2>Session Manager</h2>
            <div className="session-list">
              {sessions.map((session) => (
                <button
                  key={session.session_id}
                  className={`session-item ${selectedSession?.session.session_id === session.session_id ? "active" : ""}`}
                  onClick={() => {
                    void refreshSessions(session.session_id);
                    setView("workspace");
                  }}
                >
                  <span>{session.session_name}</span>
                  <small>{session.categories.join(", ") || "Uncategorized"}</small>
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className={`app-shell ${taskPanelOpen ? "task-panel-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <p className="eyebrow">PaperReader</p>
          <h1>Session Files</h1>
        </div>
        <button className="secondary-button" onClick={() => setView("sessions")}>All Sessions</button>
        {!selectedSession ? (
          <div className="panel empty-state">
            <h2>No session selected</h2>
            <p>Create or open a session from the session manager.</p>
          </div>
        ) : (
          <>
            <section className="panel">
              <h2>{selectedSession.session.session_name}</h2>
              <p className="subtle">{selectedSession.session.categories.join(", ") || "Uncategorized"}</p>
              <input
                type="file"
                multiple
                onChange={(event) => setUploadFiles(Array.from(event.target.files ?? []))}
              />
              <button onClick={() => void onUpload()} disabled={loading || uploadFiles.length === 0}>
                Upload Papers
              </button>
            </section>
            <section className="panel file-manager">
              <h3>Current Session File Manager</h3>
              {Object.entries(filesByCategory).map(([category, files]) => (
                <div key={category} className="file-group">
                  <h4>{category}</h4>
                  <ul className="plain-list compact-list">
                    {files.map((file) => (
                      <li key={file.file_id}>
                        <strong>{file.label}</strong>
                        <div className="subtle">{file.path}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
            <section className="panel">
              <h3>Localized References</h3>
              <ul className="plain-list compact-list">
                {selectedSession.artifacts.references.map((reference) => {
                  const primaryAccessUrl = getPrimaryAccessUrl(reference);
                  return (
                    <li key={reference.reference_id}>
                      <strong>{reference.title}</strong>
                      <div className="subtle">{reference.source_kind}</div>
                      {primaryAccessUrl && (
                        <a href={primaryAccessUrl} target="_blank" rel="noreferrer">Open</a>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          </>
        )}
      </aside>

      <main className="workspace">
        {!selectedSession ? (
          <div className="empty-state">
            <h2>No session selected</h2>
            <p>Open the session manager to begin.</p>
          </div>
        ) : (
          <>
            <header className="workspace-header">
              <div>
                <p className="eyebrow">Current Session Runtime</p>
                <h2>{selectedSession.session.session_name}</h2>
                <p className="subtle">{selectedSession.session.categories.join(", ") || "Uncategorized"}</p>
              </div>
              <div className="workspace-actions">
                <button className="secondary-button" onClick={() => setTaskPanelOpen((current) => !current)}>
                  {taskPanelOpen ? "Hide Tasks" : "Show Tasks"}
                </button>
                <button className="archive-button" onClick={() => void onArchive()} disabled={loading}>
                  Generate Archive
                </button>
              </div>
            </header>

            <section className="panel run-panel">
              <div className="run-panel-header">
                <div>
                  <p className="eyebrow">Active Runtime</p>
                  <h3>{activeRun?.mode ?? "recent"} run</h3>
                </div>
                <div className={`status-chip ${latestRunStatus === "running" ? "status-running" : latestRunStatus === "completed" ? "status-completed" : latestRunStatus === "failed" ? "status-failed" : ""}`}>
                  {latestRunStatus ?? "idle"}
                </div>
              </div>
              {activeRun?.verification_state && (
                <div className="meta-block">
                  <span>Working state version: {activeRun.working_state_version}</span>
                  <span>Verification state: {activeRun.verification_state}</span>
                  <span>Background tasks: {activeRun.active_background_task_ids.length}</span>
                </div>
              )}
              {streamedText && (
                <div className="stream-preview">
                  <pre>{streamedText}</pre>
                </div>
              )}
              <div className="event-list">
                {runEvents.map((event) => (
                  <div key={event.event_id} className="event-item">
                    <strong>{event.event_type}</strong>
                    <span>{formatRunEvent(event)}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="workspace-main-grid">
              <div className="panel runtime-column">
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
                <h3>Current Session Run</h3>
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
                <div className="divider" />
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
                {activeRun?.mode === "answer" && streamedText && (
                  <article className="qa-card streaming-card">
                    <h4>Streaming Answer</h4>
                    <p>{streamedText}</p>
                  </article>
                )}
                {latestVerification && (
                  <div className="verification-banner">
                    <strong>Latest verification</strong>
                    <div>{latestVerification.status}: {latestVerification.rationale}</div>
                  </div>
                )}
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
              </div>

              <div className="panel discovery-column">
                <h3>Find Papers</h3>
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
                          <span className="status-chip">{result.source_kind}</span>
                        </div>
                        <div className="meta-block">
                          <span>{result.venue || "Unknown venue"}</span>
                          <span>{result.year ?? "N/A"}</span>
                          <span>Citations: {result.citation_count ?? "N/A"}</span>
                        </div>
                        {result.summary && <p className="subtle">{result.summary}</p>}
                        <div className="link-row">
                          {result.landing_page_url && (
                            <a href={result.landing_page_url} target="_blank" rel="noreferrer">Open Landing</a>
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

      {selectedSession && (
        <aside className={`task-panel ${taskPanelOpen ? "visible" : ""}`}>
          <div className="task-panel-header">
            <div>
              <p className="eyebrow">Background Tasks</p>
              <h3>Task Drawer</h3>
            </div>
            <button className="secondary-button" onClick={() => setTaskPanelOpen(false)}>Close</button>
          </div>
          <div className="task-list">
            {visibleTasks.length === 0 ? (
              <p className="subtle">No background tasks yet.</p>
            ) : (
              visibleTasks.map((task) => (
                <article key={task.task_id} className="task-card">
                  <div className="task-card-header">
                    <div>
                      <strong>{task.agent_kind}</strong>
                      <div className="subtle">{task.current_step ?? task.status}</div>
                    </div>
                    <span className={`status-chip ${task.status === "running" ? "status-running" : task.status === "completed" ? "status-completed" : task.status === "failed" ? "status-failed" : ""}`}>
                      {task.status}
                    </span>
                  </div>
                  <div className="task-progress">
                    <div className="task-progress-bar">
                      <div className="task-progress-fill" style={{ width: `${task.progress}%` }} />
                    </div>
                    <span>{task.progress}%</span>
                  </div>
                  {task.output_preview && <p>{task.output_preview}</p>}
                  <div className="event-list">
                    {(taskEvents[task.task_id] ?? []).map((event) => (
                      <div key={event.event_id} className="event-item">
                        <strong>{event.event_type}</strong>
                        <span>{formatTaskEvent(event)}</span>
                      </div>
                    ))}
                  </div>
                  <div className="task-actions">
                    {!isTaskTerminal(task) && (
                      <button onClick={() => void onStopTask(task.task_id)}>Stop Task</button>
                    )}
                  </div>
                </article>
              ))
            )}
          </div>
        </aside>
      )}
    </div>
  );
}

