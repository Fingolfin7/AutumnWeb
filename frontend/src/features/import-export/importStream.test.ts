import { classifyMessage, isFinal, parseEvent, parseSseBuffer, projectProgress, succeeded } from "./importStream";

describe("importStream", () => {
  it("classifies lines like the old page", () => {
    expect(classifyMessage("Error: Invalid JSON file")).toBe("error");
    expect(classifyMessage("Import completed successfully!")).toBe("success");
    expect(classifyMessage("Warning: overlapping session")).toBe("warning");
    expect(classifyMessage("Processing 2 sessions for Foo")).toBe("info");
  });

  it("reads project progress", () => {
    expect(projectProgress("Processing project 3/12: Foo")).toEqual({ current: 3, total: 12, percent: 25 });
    expect(projectProgress("Processing 3 sessions")).toBeNull();
    expect(projectProgress("Processing project 1/0: x")).toBeNull();
  });

  it("knows when the stream is over", () => {
    expect(isFinal("Import completed successfully!")).toBe(true);
    expect(isFinal("Import completed with skipped projects: A")).toBe(true);
    expect(isFinal("Error: boom")).toBe(true);
    expect(isFinal("Processing project 1/2: A")).toBe(false);
    expect(succeeded("Import completed with skipped projects: A")).toBe(false);
    expect(succeeded("Import completed successfully!")).toBe(true);
  });

  it("parses event payloads", () => {
    expect(parseEvent('{"message":"hi"}')).toBe("hi");
    expect(parseEvent("plain")).toBe("plain");
  });

  it("splits a byte stream into events, keeping a partial one", () => {
    const first = parseSseBuffer('data: {"message":"a"}\n\ndata: {"mess');
    expect(first.messages).toEqual(["a"]);
    const second = parseSseBuffer(first.rest + 'age":"b"}\r\n\r\n: keep-alive\n\n');
    expect(second.messages).toEqual(["b"]);
    expect(second.rest).toBe("");
  });
});
