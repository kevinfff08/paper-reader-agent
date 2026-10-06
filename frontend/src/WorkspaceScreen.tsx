import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Markdown from "./Markdown";
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


type RunEventMeta = {
  icon: string;
  title: string;
  detail: string | null;
  tone: "neutral" | "active" | "success" | "danger";
};

// Human-readable presentation for the runtime timeline. `assistant_delta`
// events are intentionally not handled here: they are token-level streaming
// chunks and are filtered out of the feed (the streamed text is shown in full
// in the analysis panel instead).
function describeRunEvent(event: RunEvent): RunEventMeta {
  switch (event.event_type) {
    case "run_started":
      return { icon: "▶", title: "Run started", detail: `${String(event.payload.mode ?? "run")} mode`, tone: "active" };
    case "tool_call_started":
      return { icon: "⚙", title: "Tool started", detail: String(event.payload.tool ?? "tool"), tone: "active" };
    case "tool_call_finished":
      return { icon: "✓", title: "Tool finished", detail: String(event.payload.tool ?? "tool"), tone: "neutral" };
    case "evidence_added":
      return { icon: "❝", title: "Evidence added", detail: String(event.payload.label ?? "evidence"), tone: "neutral" };
    case "verification_required":
      return { icon: "⚠", title: "Verification requested", detail: String(event.payload.question ?? "review needed"), tone: "active" };
    case "memory_updated":
      return { icon: "✎", title: "Memory updated", detail: null, tone: "neutral" };
    case "run_completed":
      return { icon: "✔", title: "Run completed", detail: null, tone: "success" };
    case "run_failed":
      return { icon: "✕", title: "Run failed", detail: String(event.payload.error ?? "unknown error"), tone: "danger" };
    default:
      return { icon: "•", title: event.event_type.replace(/_/g, " "), detail: null, tone: "neutral" };
  }
}

const CATEGORY_META: Record<string, { label: string; icon: string; hint: string }> = {
  paper: { label: "Papers", icon: "📄", hint: "Uploaded source documents" },
  parsed: { label: "Parsed Text", icon: "🧩", hint: "Structured text extracted from papers" },
  analysis: { label: "Analyses", icon: "🧠", hint: "Generated reading analyses" },
  reference: { label: "References", icon: "🔗", hint: "Localized external references" },
  memory: { label: "Memory", icon: "💾", hint: "Session memory, notes & summaries" },
  task: { label: "Tasks", icon: "⚙️", hint: "Background task records" },
  archive: { label: "Archive", icon: "📦", hint: "Exported session archive" },
};

const CATEGORY_ORDER = ["paper", "parsed", "analysis", "reference", "memory", "task", "archive"];

const MEMORY_FILE_NAMES: Record<string, string> = {
  "memory.md": "Session memory",
  "notes.json": "Verification notes",
  "summaries.json": "Compaction summaries",
  "working_state.json": "Working state",
};

// Stored paper names embed the internal id ("206274018c4d_2605.02087v1"); drop
// the leading id so the user sees the original document name.
function cleanPaperName(name: string): string {
  return name.replace(/^[0-9a-f]{8,}_/i, "");
}

function fileKindBadge(label: string): string {
  const ext = label.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "PDF";
  if (ext === "md") return "Markdown";
  if (ext === "json") return "JSON";
  if (ext === "txt") return "Text";
  return ext.toUpperCase() || "FILE";
}

type ResolverMaps = {
  papers: Map<string, string>;
  analyses: Map<string, string>;
  references: Map<string, string>;
  tasks: Map<string, string>;
};

// Turns an opaque hashed file name (e.g. "206274018c4d.json") into a readable
// title by resolving the leading asset id against the session artifacts.
function resolveFileTitle(file: SessionFileEntry, maps: ResolverMaps): string {
  const stem = file.label.replace(/\.[^.]+$/, "");
  const leadingId = stem.split("_")[0];

  switch (file.category) {
    case "paper": {
      const paper = maps.papers.get(leadingId);
      const original = stem.includes("_") ? stem.slice(leadingId.length + 1) : null;
      return cleanPaperName(paper ?? original ?? file.label);
    }
    case "parsed": {
      const paper = maps.papers.get(leadingId) ?? maps.papers.get(stem);
      return paper ? `Parsed · ${cleanPaperName(paper)}` : "Parsed document";
    }
    case "analysis": {
      const analysis = maps.analyses.get(leadingId) ?? maps.analyses.get(stem);
      return analysis ? analysis.replace(/[0-9a-f]{8,}_/gi, "") : "Analysis";
    }
    case "reference": {
      return maps.references.get(leadingId) ?? maps.references.get(stem) ?? "Reference";
    }
    case "memory":
      return MEMORY_FILE_NAMES[file.label] ?? stem;
    case "task": {
      const kind = maps.tasks.get(leadingId) ?? maps.tasks.get(stem);
      return kind ? `${kind.replace(/_/g, " ")} task` : "Background task";
    }
    case "archive":
      return "Session archive";
    default:
      return file.label;
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
  const [readerBackground, setReaderBackground] = useState("");
  const [readingGoal, setReadingGoal] = useState("");
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
  const [activePanel, setActivePanel] = useState<"discussion" | "discovery" | "files" | "tasks" | null>(null);
  const [panelPinned, setPanelPinned] = useState(true);
  const [taskEvents, setTaskEvents] = useState<Record<string, TaskEvent[]>>({});
  const questionInputRef = useRef<HTMLTextAreaElement | null>(null);
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
        categories: categories.split(",").map((item) => item.trim()).filter(Boolean),
        background: readerBackground.trim() || undefined,
        user_goal: readingGoal.trim() || undefined
      });
      setSessionName("");
      setCategories("");
      setReaderBackground("");
      setReadingGoal("");
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
        if (event.event_type === "assistant_delta") {
          // Token-level chunks accumulate into the streamed text only; they are
          // intentionally kept out of the lifecycle event feed.
          const delta = String(event.payload.delta ?? "");
          setStreamedText((current) => current + delta);
        } else {
          setRunEvents((current) => [...current, event].slice(-12));
        }
        if (event.event_type === "run_started") {
          setActiveRun((current) => current ? { ...current, status: "running" } : current);
        }
        if (event.event_type === "run_completed" || event.event_type === "run_failed") {
          source.close();
          runSourceRef.current = null;
          void refreshSessions(selectedSession.session.session_id);
          setLoading(false);
          setActiveRun((current) =>
            current ? { ...current, status: event.event_type === "run_completed" ? "completed" : "failed",
              error_message: event.event_type === "run_failed" ? String(event.payload.error ?? "生成失败，请稍后重试。") : null } : current
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
  const resolverMaps = useMemo<ResolverMaps>(() => {
    const artifacts = selectedSession?.artifacts;
    return {
      papers: new Map(
        (artifacts?.papers ?? []).map((paper) => [paper.paper_id, paper.title || paper.filename])
      ),
      analyses: new Map(
        (artifacts?.analyses ?? []).map((analysis) => [analysis.analysis_id, analysis.title])
      ),
      references: new Map(
        (artifacts?.references ?? []).map((reference) => [reference.reference_id, reference.title])
      ),
      tasks: new Map(
        (artifacts?.tasks ?? []).map((task) => [task.task_id, task.agent_kind])
      ),
    };
  }, [selectedSession]);
  const orderedFileCategories = useMemo(() => {
    const rank = (category: string) => {
      const position = CATEGORY_ORDER.indexOf(category);
      return position === -1 ? CATEGORY_ORDER.length : position;
    };
    return Object.keys(filesByCategory).sort((a, b) => rank(a) - rank(b));
  }, [filesByCategory]);
  const visibleRunEvents = useMemo(
    () => runEvents.filter((event) => event.event_type !== "assistant_delta"),
    [runEvents]
  );
  const isRunStreaming = latestRunStatus === "running";
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
            <input aria-label="阅读背景" placeholder="你的背景（可选）：例如熟悉机器学习，初次接触强化学习"
              value={readerBackground} onChange={(event) => setReaderBackground(event.target.value)} />
            <input aria-label="阅读目标" placeholder="阅读目标（可选）：例如理解核心想法，或准备复现方法"
              value={readingGoal} onChange={(event) => setReadingGoal(event.target.value)} />
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

  const tools = [["discussion", "讨论"], ["discovery", "找论文"], ["files", "文件"], ["tasks", "任务"]] as const;
  return (
    <div className={`reader-shell ${activePanel ? "panel-open" : ""} ${panelPinned ? "panel-pinned" : ""}`}
      onKeyDown={(event) => { if (event.key === "Escape") setActivePanel(null); }}>
      <aside className="reader-nav" aria-label="会话导航">
        <div className="reader-brand">PaperReader<span>研究，从读懂开始</span></div>
        <button className="secondary-button" onClick={() => setView("sessions")}>所有会话</button>
        {selectedSession ? <>
          <div className="nav-section-label">当前会话</div>
          <strong className="nav-session-title">{selectedSession.session.session_name}</strong>
          <p className="subtle">{selectedSession.session.categories.join(" / ") || "未分类"}</p>
          <div className="nav-section-label">论文 · {selectedSession.artifacts.papers.length}</div>
          <ul className="paper-nav-list">{selectedSession.artifacts.papers.map((paper) =>
            <li key={paper.paper_id}>{cleanPaperName(paper.title || paper.filename)}</li>)}</ul>
          <details className="upload-control"><summary>添加论文</summary>
            <input aria-label="选择论文文件" type="file" multiple onChange={(event) => setUploadFiles(Array.from(event.target.files ?? []))} />
            <button onClick={() => void onUpload()} disabled={loading || uploadFiles.length === 0}>上传论文</button>
          </details>
          <details className="reader-profile"><summary>阅读背景与目标</summary>
            <p>{selectedSession.session.background || "尚未填写阅读背景"}</p>
            <p>{selectedSession.session.user_goal || "尚未填写阅读目标"}</p>
          </details>
        </> : <p className="subtle">创建会话，开始阅读。</p>}
      </aside>
      <main className="reader-workspace">
        <header className="reader-toolbar">
          <span className="reader-location">阅读工作台</span>
          <nav className="utility-tabs" aria-label="阅读工具">{tools.map(([key, label]) =>
            <button key={key} className="secondary-button" aria-pressed={activePanel === key} aria-controls={`tool-${key}`}
              onClick={() => setActivePanel(activePanel === key ? null : key)}>{label}{key === "tasks" && visibleTasks.some((task) => !isTaskTerminal(task)) && <span className="activity-dot" aria-label="任务进行中" />}</button>)}</nav>
          <button className="secondary-button" onClick={() => void onArchive()} disabled={!selectedSession || loading}>归档</button>
        </header>
        {selectedSession ? <>
          <div className="reader-status" role="status">{isRunStreaming ? "正在生成，请稍候…" : latestRunStatus === "failed" ? "生成未完成，请查看错误信息" : ""}</div>
          <div className="reading-document">
                <div className="analysis-actions">
                  <input
                    placeholder="你最想弄懂什么？（可选）"
                    value={focusQuestion}
                    onChange={(event) => setFocusQuestion(event.target.value)}
                  />
                  <button onClick={() => void onAnalyze()} disabled={loading || selectedSession.artifacts.papers.length === 0}>
                    生成阅读导引
                  </button>
                </div>
                <h3>读懂这篇论文</h3>
                {activeRun?.status === "failed" && (
                  <p role="alert">{activeRun.error_message || "生成失败，请检查模型配置后重试。"}</p>
                )}
                {activeRun?.mode === "analyze" && streamedText && isRunStreaming ? (
                  <article className="analysis-section">
                    <div className="analysis-section-head">
                      <h4>Streaming Analysis Draft</h4>
                      {isRunStreaming && <span className="streaming-tag">Streaming…</span>}
                    </div>
                    <Markdown content={streamedText} />
                  </article>
                ) : latestAnalysis ? (
                  latestAnalysis.sections.map((section) => {
                    const startsWithHeading = section.content.trim().startsWith("#");
                    return (
                      <article key={section.key} className="analysis-section">
                        {!startsWithHeading && <h4>{section.title}</h4>}
                        <Markdown content={section.content} />
                      </article>
                    );
                  })
                ) : (
                  <p className="subtle">Upload papers and run analysis to populate this workspace.</p>
                )}

          </div>
          <footer className="reading-footer"><button className="secondary-button" onClick={() => setActivePanel("discussion")}>有疑问？继续讨论 →</button>
            {selectedSession.artifacts.archive?.markdown_path && <p className="archive-path">归档已生成：<code>{selectedSession.artifacts.archive.markdown_path}</code></p>}
          </footer>
        </> : <div className="empty-state"><h2>把论文读成自己的理解</h2><p>创建一个会话，添加想读的论文。</p><button onClick={() => setView("sessions")}>创建会话</button></div>}
      </main>
      <aside className="utility-panel" hidden={!activePanel} aria-label="辅助面板">
        <header className="utility-panel-header"><strong>{tools.find(([key]) => key === activePanel)?.[1]}</strong>
          <button className="secondary-button" aria-pressed={panelPinned} onClick={() => setPanelPinned(!panelPinned)}>{panelPinned ? "取消固定" : "固定面板"}</button>
          <button className="secondary-button" onClick={() => setActivePanel(null)} aria-label="关闭辅助面板">关闭</button>
        </header>
        {selectedSession && <>
          <section id="tool-discussion" className="utility-content" hidden={activePanel !== "discussion"} aria-label="论文讨论">
                <p className="subtle">哪里还没懂？选择一个方向，或直接写下你的困惑。</p>
                <div className="reading-shortcuts">
                  {[
                    ["通俗概括", "请用通俗语言解释论文的核心想法，先讲问题、直觉和价值，不展开实现细节。"],
                    ["理清论证", "这篇论文最关键的思想转折是什么？请根据它实际使用的推导、反例或实验，解释前提如何通向结论，而不只是罗列方法步骤。"],
                    ["举个例子", "请优先用论文中的一个例子解释刚才讨论的核心思想。如果需要自拟教学示例，请标明，并说明它能解释什么、不能说明什么。"],
                    ["解释公式", "请解释论文的关键公式：它在论证中起什么作用、依赖哪些前提、每个符号是什么意思，以及直觉。若有多个公式，先讲最核心的一个。"],
                    ["看懂贡献", "相对论文讨论的已有工作，它改变了哪个假设、方法或认识？请讲清真正的新意以及没有解决的问题，不只比较工程复杂度。"],
                    ["看懂实验", "请选择一个决定性的实验，解释改变与固定了什么、对照为何合理、结果支持哪项主张，以及哪些解释还不能排除。"],
                    ["研究启发", "从本文一个具体未决问题出发，提出一个后续研究问题，并说明怎样用最小对照或推导区分两种可能解释。请区分论文结论与你的推测，不宣称已验证新颖性。"],
                    ["检查理解", "请围绕论文核心思想给我三个自测问题，先不要给答案，等我回答后再帮我纠正。"],
                  ].map(([label, prompt]) => (
                    <button type="button" className="secondary-button" key={label} disabled={loading}
                      onClick={() => { setQuestion(prompt); questionInputRef.current?.focus(); }}>{label}</button>
                  ))}
                </div>
                <form onSubmit={onAskQuestion} className="qa-form">
                  <textarea
                    ref={questionInputRef}
                    placeholder="例如：为什么要加这一步？我不理解这个公式的直觉。"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                  />
                  <button type="submit" disabled={loading || !question.trim()}>
                    Ask
                  </button>
                </form>
                {activeRun?.mode === "answer" && streamedText && (
                  <article className="qa-card streaming-card">
                    <div className="analysis-section-head">
                      <h4>Streaming Answer</h4>
                      {isRunStreaming && <span className="streaming-tag">Streaming…</span>}
                    </div>
                    <Markdown content={streamedText} />
                  </article>
                )}
                {latestVerification && (
                  <details className="verification-banner"><summary>查看原文检查信息</summary>
                    <strong>Latest verification</strong>
                    <div>{latestVerification.status}: {latestVerification.rationale}</div>
                  </details>
                )}
                <div className="qa-list">
                  {qaRecords.map((record) => (
                    <article key={record.question_id} className="qa-card">
                      <h4>{record.question_text}</h4>
                      <Markdown content={record.answer_text} />
                      <div className="meta-block">
                        <span>Verification: {record.verification_status}</span>
                        <span>Evidence: {record.evidence_refs.length}</span>
                        <span>New refs: {record.retrieval_refs.length}</span>
                      </div>
                    </article>
                  ))}
                </div>

          </section>
          <section id="tool-discovery" className="utility-content" hidden={activePanel !== "discovery"} aria-label="文献搜索">
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

          </section>
          <section id="tool-files" className="utility-content" hidden={activePanel !== "files"} aria-label="会话文件">
            <section className="panel file-manager">
              <h3>Current Session File Manager</h3>
              {orderedFileCategories.length === 0 && (
                <p className="subtle">No files yet. Upload papers to get started.</p>
              )}
              {orderedFileCategories.map((category) => {
                const files = filesByCategory[category];
                const meta = CATEGORY_META[category] ?? { label: category, icon: "📁", hint: "" };
                return (
                  <div key={category} className="file-group">
                    <div className="file-group-head">
                      <span className="file-group-icon">{meta.icon}</span>
                      <div>
                        <h4>
                          {meta.label}
                          <span className="file-count">{files.length}</span>
                        </h4>
                        {meta.hint && <p className="file-group-hint">{meta.hint}</p>}
                      </div>
                    </div>
                    <ul className="file-list">
                      {files.map((file) => (
                        <li key={file.file_id} className="file-item" title={file.path}>
                          <span className="file-kind">{fileKindBadge(file.label)}</span>
                          <div className="file-item-body">
                            <strong>{resolveFileTitle(file, resolverMaps)}</strong>
                            <code className="file-name">{file.label}</code>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
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

          </section>
          <section id="tool-tasks" className="utility-content" hidden={activePanel !== "tasks"} aria-label="运行与任务">
            <details className="panel run-panel">
              <summary>运行详情（需要时展开）</summary>
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
              {isRunStreaming && (
                <div className="streaming-indicator">
                  <span className="streaming-dot" />
                  Streaming response… see “读懂这篇论文” below.
                </div>
              )}
              {visibleRunEvents.length === 0 ? (
                <p className="subtle">Run events will appear here.</p>
              ) : (
                <div className="event-feed">
                  {visibleRunEvents.map((event) => {
                    const meta = describeRunEvent(event);
                    return (
                      <div key={event.event_id} className={`event-row tone-${meta.tone}`}>
                        <span className="event-icon">{meta.icon}</span>
                        <div className="event-body">
                          <strong>{meta.title}</strong>
                          {meta.detail && <span>{meta.detail}</span>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </details>

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

          </section>
        </>}
      </aside>
    </div>
  );
}
