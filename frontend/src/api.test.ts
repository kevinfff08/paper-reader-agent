import { afterEach, expect, it, vi } from "vitest";
import { listSessions, runEventsUrl, taskEventsUrl } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("keeps API and event requests on the current application origin", async () => {
  const fetch = vi.fn().mockResolvedValue({ json: async () => ({ sessions: [] }) });
  vi.stubGlobal("fetch", fetch);
  expect(await listSessions()).toEqual([]);
  expect(fetch).toHaveBeenCalledWith("/sessions");
  expect(runEventsUrl("session", "run")).toBe("/sessions/session/runs/run/events");
  expect(taskEventsUrl("session", "task")).toBe("/sessions/session/tasks/task/events");
});
