import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import WorkspaceScreen from "./WorkspaceScreen";
import * as api from "./api";
import type { RunEvent, SessionDetailResponse, SessionSummary, TaskEvent } from "./types";


vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    listSessions: vi.fn(),
    createSession: vi.fn(),
    discoverLiterature: vi.fn(),
    getSession: vi.fn(),
    localizeDiscoveryReference: vi.fn(),
    uploadPapers: vi.fn(),
    createRun: vi.fn(),
    runEventsUrl: vi.fn(),
    stopTask: vi.fn(),
    taskEventsUrl: vi.fn(),
  };
});


class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  emit(payload: RunEvent | TaskEvent) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }

  close() {
    this.closed = true;
  }
}


const mockedApi = vi.mocked(api);

const sessionSummary: SessionSummary = {
  session_id: "session-1",
  session_name: "Test Session",
  session_slug: "test-session",
  categories: ["ml"],
  user_goal: "Read carefully",
  background: null,
  external_links: [],
  created_at: "2026-04-13T00:00:00Z",
  updated_at: "2026-04-13T00:00:00Z",
};

const sessionDetail: SessionDetailResponse = {
  session: sessionSummary,
  artifacts: {
    papers: [
      {
        paper_id: "paper-1",
        filename: "sample.pdf",
        original_path: "D:/tmp/sample.pdf",
        title: "Sample Paper",
      },
    ],
    references: [],
    analyses: [],
    qa_records: [],
    memory: null,
    evidence_ledger: [],
    compact_summaries: [],
    library_cards: [],
    verification_memory: [],
    literature_searches: [],
    runs: [],
    tasks: [],
    session_files: [
      {
        file_id: "file-1",
        label: "sample.pdf",
        path: "D:/tmp/sample.pdf",
        category: "paper",
        updated_at: "2026-04-13T00:00:00Z",
      },
    ],
    archive: null,
  },
};


describe("WorkspaceScreen", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.clearAllMocks();
    mockedApi.listSessions.mockResolvedValue([sessionSummary]);
    mockedApi.getSession.mockResolvedValue(sessionDetail);
    mockedApi.discoverLiterature.mockResolvedValue({
      search_id: "search-1",
      session_id: "session-1",
      query: "transformer",
      discovery_mode: "seminal",
      domain: "cs",
      preferred_venues: [],
      results: [
        {
          result_id: "result-1",
          title: "Attention Is All You Need",
          authors: ["Ashish Vaswani"],
          year: 2017,
          venue: "NeurIPS",
          source_kind: "openalex",
          source_url: "https://example.org/paper",
          citation_count: 1000,
          summary: "A seminal transformer paper.",
          landing_page_url: "https://example.org/paper",
          best_access_url: "https://example.org/paper",
          manual_search_url: "https://www.google.com/search?q=attention",
          acquisition_status: "remote_landing_only",
        },
      ],
      created_at: "2026-04-13T00:00:00Z",
    });
    mockedApi.localizeDiscoveryReference.mockResolvedValue({
      reference_id: "ref-1",
      title: "Attention Is All You Need",
      source_kind: "openalex",
      source_url: "https://example.org/paper",
      summary: "A seminal transformer paper.",
      best_access_url: "https://example.org/paper",
    });
    mockedApi.createRun.mockResolvedValue({
      run: {
        run_id: "run-1",
        session_id: "session-1",
        mode: "analyze",
        status: "pending",
        input_text: "Focus question",
        preferred_paper_ids: [],
        risk_level: null,
        working_state_version: 1,
        active_background_task_ids: ["task-1"],
        verification_state: "not_requested",
        final_artifact_ref: null,
        error_message: null,
        created_at: "2026-04-13T00:00:00Z",
        updated_at: "2026-04-13T00:00:00Z",
      },
    });
    mockedApi.runEventsUrl.mockReturnValue("http://127.0.0.1:8000/events");
    mockedApi.taskEventsUrl.mockReturnValue("http://127.0.0.1:8000/task-events");
    mockedApi.stopTask.mockResolvedValue({
      task: {
        task_id: "task-1",
        session_id: "session-1",
        agent_kind: "compact",
        status: "cancelled",
        input_text: "compact",
        progress: 40,
        result_payload: {},
        created_at: "2026-04-13T00:00:00Z",
        updated_at: "2026-04-13T00:00:04Z",
      },
    });
    vi.stubGlobal("EventSource", MockEventSource);
  });

  it("loads the first session into the workspace", async () => {
    render(<WorkspaceScreen />);

    expect((await screen.findAllByText("Test Session")).length).toBeGreaterThan(0);
    expect(screen.getByText("生成阅读导引")).toBeInTheDocument();
    expect(screen.getByText("会话文件")).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "文件" }));
    expect(screen.getByText("会话文件")).toBeVisible();
    expect(mockedApi.listSessions).toHaveBeenCalled();
    expect(mockedApi.getSession).toHaveBeenCalledWith("session-1");
  });

  it("retains session creation with reading background and goal", async () => {
    mockedApi.createSession.mockResolvedValueOnce(sessionDetail);
    render(<WorkspaceScreen />);
    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByRole("button", { name: "所有会话" }));
    fireEvent.change(screen.getByLabelText("会话名称"), { target: { value: "My reading" } });
    fireEvent.change(screen.getByLabelText("分类标签"), { target: { value: "theory, ml" } });
    fireEvent.change(screen.getByLabelText("阅读背景"), { target: { value: "PhD student" } });
    fireEvent.change(screen.getByLabelText("阅读目标"), { target: { value: "Understand assumptions" } });
    fireEvent.click(screen.getByRole("button", { name: "创建会话" }));
    await waitFor(() => expect(mockedApi.createSession).toHaveBeenCalledWith({
      session_name: "My reading", categories: ["theory", "ml"], background: "PhD student", user_goal: "Understand assumptions",
    }));
    expect(await screen.findByRole("button", { name: "生成阅读导引" })).toBeVisible();
  });

  it("retains multi-file upload and the archive operation", async () => {
    mockedApi.uploadPapers.mockResolvedValueOnce(sessionDetail);
    render(<WorkspaceScreen />);
    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByText("添加论文"));
    const files = [new File(["first"], "first.txt"), new File(["second"], "second.txt")];
    fireEvent.change(screen.getByLabelText("选择论文文件"), { target: { files } });
    fireEvent.click(screen.getByRole("button", { name: "上传论文" }));
    await waitFor(() => expect(mockedApi.uploadPapers).toHaveBeenCalledWith("session-1", files));
    await waitFor(() => expect(screen.getByRole("button", { name: "归档" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "归档" }));
    await waitFor(() => expect(mockedApi.createRun).toHaveBeenCalledWith("session-1", {
      mode: "archive", input: "build archive", preferred_paper_ids: [],
    }));
  });

  it("preserves drafts and search filters when switching and closing panels", async () => {
    render(<WorkspaceScreen />);
    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByRole("button", { name: "讨论" }));
    const draft = screen.getByPlaceholderText("例如：为什么要加这一步？我不理解这个公式的直觉。");
    fireEvent.change(draft, { target: { value: "Explain this assumption" } });
    fireEvent.click(screen.getByRole("button", { name: "找论文" }));
    const search = screen.getByPlaceholderText("搜索论文、主题或会议");
    fireEvent.change(search, { target: { value: "preference learning" } });
    fireEvent.click(screen.getByRole("button", { name: "关闭辅助面板" }));
    expect(search).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "讨论" }));
    expect(draft).toHaveValue("Explain this assumption");
    fireEvent.click(screen.getByRole("button", { name: "找论文" }));
    expect(search).toHaveValue("preference learning");
    expect(mockedApi.createRun).not.toHaveBeenCalled();
  });

  it("switches between single-paper guides, comparison and historical versions", async () => {
    const guide = (id: string, paper_ids: string[], title: string) => ({ analysis_id: id, paper_ids, title,
      markdown_path: "guide.md", created_at: "2026-04-13T00:00:00Z",
      sections: [{ key: "core", title: "核心论证", content: `${id} explanation` }] });
    mockedApi.getSession.mockResolvedValue({ ...sessionDetail, artifacts: { ...sessionDetail.artifacts,
      papers: [...sessionDetail.artifacts.papers, { paper_id: "p2", filename: "second.pdf", title: "Second Paper", original_path: "second.pdf" }],
      analyses: [guide("first", ["paper-1"], "First Guide"), guide("second", ["p2"], "Second Guide"), guide("both", ["paper-1", "p2"], "Comparison")],
    }});
    render(<WorkspaceScreen />);
    expect(await screen.findByText("both explanation")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Sample Paper" }));
    expect(screen.getByText("first explanation")).toBeVisible();
    expect(screen.queryByText("both explanation")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "跨篇比较" }));
    expect(screen.getByText("both explanation")).toBeVisible();
    fireEvent.change(screen.getByLabelText("选择导读或历史版本"), { target: { value: "second" } });
    expect(screen.getByText("second explanation")).toBeVisible();
    fireEvent.click(screen.getByText("章节目录 · 1"));
    expect(screen.getByRole("link", { name: "核心论证" })).toHaveAttribute("href", "#section-second-0");
    fireEvent.click(screen.getByRole("button", { name: "讨论" }));
    fireEvent.change(screen.getByLabelText("论文问题"), { target: { value: "Explain this paper" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));
    await waitFor(() => expect(mockedApi.createRun).toHaveBeenCalledWith("session-1", {
      mode: "answer", input: "Explain this paper", preferred_paper_ids: ["p2"],
    }));
  });

  it("keeps the question available after a failed request", async () => {
    mockedApi.createRun.mockRejectedValueOnce(new Error("Network unavailable"));
    render(<WorkspaceScreen />);
    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByRole("button", { name: "讨论" }));
    fireEvent.change(screen.getByLabelText("论文问题"), { target: { value: "Explain the assumption" } });
    fireEvent.click(screen.getByRole("button", { name: "发送问题" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Network unavailable");
    expect(screen.getByLabelText("论文问题")).toHaveValue("Explain the assumption");
  });

  it("streams run output and shows runtime events", async () => {
    render(<WorkspaceScreen />);

    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByText("生成阅读导引"));

    await waitFor(() => expect(mockedApi.createRun).toHaveBeenCalledWith("session-1", {
      mode: "analyze",
      input: "",
      preferred_paper_ids: [],
    }));

    mockedApi.getSession.mockResolvedValue({ ...sessionDetail, artifacts: {
      ...sessionDetail.artifacts,
      analyses: [{ analysis_id: "a", paper_ids: ["paper-1"],
        title: "Reading guide", markdown_path: "guide.md", created_at: "2026-04-13T00:00:00Z",
        sections: [{ key: "core_contribution", title: "Overview", content: "Complete guide overview" },
                   { key: "method_details", title: "Method", content: "Complete method explanation" }] }],
    }});
    const source = MockEventSource.instances[0];
    await act(async () => {
      source.emit({
        event_id: "evt-1",
        run_id: "run-1",
        sequence_number: 1,
        event_type: "run_started",
        payload: { mode: "analyze" },
        created_at: "2026-04-13T00:00:01Z",
      });
      source.emit({
        event_id: "evt-2",
        run_id: "run-1",
        sequence_number: 2,
        event_type: "assistant_delta",
        payload: { delta: "Streaming output" },
        created_at: "2026-04-13T00:00:02Z",
      });
      source.emit({
        event_id: "evt-3",
        run_id: "run-1",
        sequence_number: 3,
        event_type: "run_completed",
        payload: { status: "completed" },
        created_at: "2026-04-13T00:00:03Z",
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /任务/ }));
    expect(await screen.findByText("当前运行")).toBeInTheDocument();
    expect(await screen.findByText("Complete method explanation")).toBeInTheDocument();
    expect(screen.queryByText("Streaming output")).not.toBeInTheDocument();
    // Token-level deltas are filtered out of the runtime feed; only lifecycle
    // events are shown with human-readable titles.
    expect(screen.queryByText("Delta: Streaming output")).not.toBeInTheDocument();
    expect(await screen.findByText("开始处理")).toBeInTheDocument();
    expect(await screen.findByText("处理完成")).toBeInTheDocument();
    await waitFor(() => expect(source.closed).toBe(true));
  });

  it("puts a teaching shortcut into the editable question without starting a run", async () => {
    render(<WorkspaceScreen />);
    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByRole("button", { name: "讨论" }));
    fireEvent.click(screen.getByText("提问方向 · 8 种"));
    fireEvent.click(screen.getByRole("button", { name: "举个例子" }));
    const input = screen.getByPlaceholderText("例如：为什么要加这一步？我不理解这个公式的直觉。");
    expect((input as HTMLTextAreaElement).value).toContain("论文中的一个例子");
    fireEvent.click(screen.getByText("提问方向 · 8 种"));
    fireEvent.click(screen.getByRole("button", { name: "理清论证" }));
    expect((input as HTMLTextAreaElement).value).toContain("前提如何通向结论");
    expect(input).toHaveFocus();
    expect(mockedApi.createRun).not.toHaveBeenCalled();
  });

  it("shows model failures beside the reading content even when details are collapsed", async () => {
    render(<WorkspaceScreen />);
    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByText("生成阅读导引"));
    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    await act(async () => MockEventSource.instances[0].emit({
      event_id: "failed", run_id: "run-1", sequence_number: 1, event_type: "run_failed",
      payload: { error: "模型不可用，请检查模型名称" }, created_at: "2026-04-13T00:00:03Z",
    }));
    expect(screen.getByRole("alert")).toHaveTextContent("模型不可用，请检查模型名称");
  });

  it("supports discovery search and renders result actions", async () => {
    render(<WorkspaceScreen />);

    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByRole("button", { name: "找论文" }));
    fireEvent.change(screen.getByPlaceholderText("搜索论文、主题或会议"), {
      target: { value: "transformer" },
    });
    fireEvent.click(screen.getByText("搜索"));

    await waitFor(() => expect(mockedApi.discoverLiterature).toHaveBeenCalledWith("session-1", {
      query: "transformer",
      discovery_mode: "latest_top_venues",
      domain: "general",
      max_results: 10,
      preferred_venues: [],
    }));

    expect(await screen.findByText("Attention Is All You Need")).toBeInTheDocument();
    expect(await screen.findByText("查看原文")).toBeInTheDocument();
    expect(await screen.findByText("保存参考文献")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存参考文献" }));
    await waitFor(() => expect(mockedApi.localizeDiscoveryReference).toHaveBeenCalledWith("session-1", "search-1", "result-1"));
  });

  it("shows the background task drawer and allows stopping a task", async () => {
    mockedApi.getSession.mockResolvedValueOnce({
      ...sessionDetail,
      artifacts: {
        ...sessionDetail.artifacts,
        tasks: [
          {
            task_id: "task-1",
            session_id: "session-1",
            agent_kind: "compact",
            status: "running",
            input_text: "compact",
            progress: 20,
            result_payload: {},
            created_at: "2026-04-13T00:00:00Z",
            updated_at: "2026-04-13T00:00:00Z",
          },
        ],
      },
    });

    render(<WorkspaceScreen />);

    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByRole("button", { name: /任务/ }));
    expect(screen.getByRole("region", { name: "运行与任务" })).toBeVisible();

    const source = MockEventSource.instances[0];
    await act(async () => {
      source.emit({
        event_id: "task-evt-1",
        task_id: "task-1",
        sequence_number: 1,
        event_type: "task_progress",
        payload: { progress: 55, current_step: "ready_for_merge" },
        created_at: "2026-04-13T00:00:01Z",
      });
    });

    expect(await screen.findByText("ready_for_merge (55%)")).toBeInTheDocument();
    fireEvent.click(screen.getByText("停止任务"));
    await waitFor(() => expect(mockedApi.stopTask).toHaveBeenCalledWith("session-1", "task-1"));
  });
});
