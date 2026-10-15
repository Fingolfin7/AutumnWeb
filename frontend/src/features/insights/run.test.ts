import { applyStreamEvent, failRun, showsRun, startRunState, stopRun } from "./run";

const fresh = () => startRunState({ id: 1, chatId: null, prompt: "What did I do?", model: "gpt-a", baseCount: 0 });

describe("applyStreamEvent", () => {
  it("follows the event sequence of a normal answer", () => {
    let run = fresh();
    run = applyStreamEvent(run, "chat", { chat_id: "c1", chat_url: "/insights/c1/", stream_url: "/insights/c1/stream/" });
    expect(run.chatId).toBe("c1");
    run = applyStreamEvent(run, "delta", { content: "You " });
    run = applyStreamEvent(run, "delta", { content: "wrote." });
    expect(run).toMatchObject({ text: "You wrote.", status: "streaming" });
    run = applyStreamEvent(run, "done", {
      chat_id: "c1",
      content: "You wrote.",
      html: "<p>You wrote.</p>",
      sources: [{ link: "https://example.com", title: "Doc" }],
      usage: { prompt: 10, response: 5 },
      model: "gpt-a-2",
      chat_title: "Writing",
    });
    expect(run).toMatchObject({ status: "done", html: "<p>You wrote.</p>", model: "gpt-a-2", usage: { prompt: 10, response: 5 } });
    expect(run.sources).toHaveLength(1);
  });

  it("keeps the streamed text when done carries none", () => {
    let run = applyStreamEvent(fresh(), "delta", { content: "partial" });
    run = applyStreamEvent(run, "done", { content: "" });
    expect(run.text).toBe("partial");
  });

  it("marks a failed-but-saved answer (done with error) and a broken stream as errors", () => {
    const saved = applyStreamEvent(applyStreamEvent(fresh(), "delta", { content: "half" }), "done", { content: "half\n\nStream error: boom", error: "boom" });
    expect(saved.status).toBe("error");
    expect(saved.text).toContain("Stream error: boom");
    const broken = applyStreamEvent(applyStreamEvent(fresh(), "delta", { content: "half" }), "error", { message: "Upstream died." });
    expect(broken).toMatchObject({ status: "error", text: "half\n\nUpstream died." });
    expect(applyStreamEvent(fresh(), "error", {}).text).toBe("Streaming failed.");
  });

  it("ignores unknown events, and failRun/stopRun behave", () => {
    const run = fresh();
    expect(applyStreamEvent(run, "ping", {})).toBe(run);
    expect(failRun(run, "offline").text).toBe("Error: offline");
    expect(stopRun(run).status).toBe("stopped");
    const done = applyStreamEvent(run, "done", { content: "x" });
    expect(stopRun(done).status).toBe("done");
  });
});

describe("showsRun", () => {
  it("shows a new chat's run on the new-chat page until its chat exists", () => {
    const run = fresh();
    expect(showsRun(run, undefined, 0)).toBe(true);
    expect(showsRun({ ...run, chatId: "c1" }, undefined, 0)).toBe(false);
    expect(showsRun({ ...run, chatId: "c1" }, "c1", 0)).toBe(true);
    expect(showsRun({ ...run, chatId: "c1" }, "c2", 0)).toBe(false);
  });

  it("hides the run once the saved messages include it", () => {
    const run = { ...fresh(), chatId: "c1", baseCount: 4 };
    expect(showsRun(run, "c1", 4)).toBe(true);
    expect(showsRun(run, "c1", 6)).toBe(false);
  });
});
