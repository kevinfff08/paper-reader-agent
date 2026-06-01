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
    expect(screen.getByText("Analyze Session")).toBeInTheDocument();
    expect(screen.getByText("Current Session File Manager")).toBeInTheDocument();
    expect(mockedApi.listSessions).toHaveBeenCalled();
    expect(mockedApi.getSession).toHaveBeenCalledWith("session-1");
  });

  it("streams run output and shows runtime events", async () => {
    render(<WorkspaceScreen />);

    await screen.findAllByText("Test Session");
    fireEvent.click(screen.getByText("Analyze Session"));

    await waitFor(() => expect(mockedApi.createRun).toHaveBeenCalledWith("session-1", {
      mode: "analyze",
      input: "",
      preferred_paper_ids: [],
    }));

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

    expect(await screen.findByText("Active Runtime")).toBeInTheDocument();
    expect((await screen.findAllByText("Streaming output")).length).toBeGreaterThan(0);
    // Token-level deltas are filtered out of the runtime feed; only lifecycle
    // events are shown with human-readable titles.
    expect(screen.queryByText("Delta: Streaming output")).not.toBeInTheDocument();
    expect(await screen.findByText("Run started")).toBeInTheDocument();
    expect(await screen.findByText("Run completed")).toBeInTheDocument();
    await waitFor(() => expect(source.closed).toBe(true));
  });

  it("supports discovery search and renders result actions", async () => {
    render(<WorkspaceScreen />);

    await screen.findAllByText("Test Session");
    fireEvent.change(screen.getByPlaceholderText("Search papers, venues, or topics"), {
      target: { value: "transformer" },
    });
    fireEvent.click(screen.getByText("Search"));

    await waitFor(() => expect(mockedApi.discoverLiterature).toHaveBeenCalledWith("session-1", {
      query: "transformer",
      discovery_mode: "latest_top_venues",
      domain: "general",
      max_results: 10,
      preferred_venues: [],
    }));

    expect(await screen.findByText("Attention Is All You Need")).toBeInTheDocument();
    expect(await screen.findByText("Open Landing")).toBeInTheDocument();
    expect(await screen.findByText("Localize Reference")).toBeInTheDocument();
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
    expect(await screen.findByText("Task Drawer")).toBeInTheDocument();

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
    fireEvent.click(screen.getByText("Stop Task"));
    await waitFor(() => expect(mockedApi.stopTask).toHaveBeenCalledWith("session-1", "task-1"));
  });
});
