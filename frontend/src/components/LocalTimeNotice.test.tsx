import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { LocalTimeNotice, useLocalTime } from "./LocalTimeNotice";

const previousZone = process.env.TZ;
beforeAll(() => {
  process.env.TZ = "Europe/Prague";
});
afterAll(() => {
  if (previousZone === undefined) delete process.env.TZ;
  else process.env.TZ = previousZone;
});

it("runs in Europe/Prague", () => {
  expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe("Europe/Prague");
  expect(new Date("2026-10-25T02:30:00").getTimezoneOffset()).toBe(-120);
});

describe("useLocalTime", () => {
  it("submits an ordinary time as is", () => {
    const { result } = renderHook(() => useLocalTime("2026-10-14T09:30:05"));
    expect(result.current.instant).toBe("2026-10-14T09:30:05+02:00");
    expect(result.current.error).toBeNull();
  });

  it("defaults a repeated time to the first and lets the second be picked", () => {
    const { result } = renderHook(() => useLocalTime("2026-10-25T02:30:00"));
    expect(result.current.candidates.kind).toBe("ambiguous");
    expect(result.current.instant).toBe("2026-10-25T02:30:00+02:00");
    act(() => result.current.setIndex(1));
    expect(result.current.instant).toBe("2026-10-25T02:30:00+01:00");
  });

  it("goes back to the first occurrence when the time is edited", () => {
    const { result, rerender } = renderHook(({ value }) => useLocalTime(value), { initialProps: { value: "2026-10-25T02:30:00" } });
    act(() => result.current.setIndex(1));
    rerender({ value: "2026-10-25T02:40:00" });
    expect(result.current.instant).toBe("2026-10-25T02:40:00+02:00");
  });

  it("keeps the occurrence an untouched field was filled from", () => {
    const { result } = renderHook(() => useLocalTime("2026-10-25T02:30:00", "2026-10-25T02:30:00.250+01:00"));
    expect(result.current.index).toBe(1);
    expect(result.current.instant).toBe("2026-10-25T02:30:00+01:00");
  });

  it("blocks a skipped time with an error and no instant", () => {
    const { result } = renderHook(() => useLocalTime("2026-03-29T02:30"));
    expect(result.current.instant).toBeNull();
    expect(result.current.error).toBe("Clocks go forward at this time, so 02:30 doesn't exist on 29 Mar.");
  });
});

describe("LocalTimeNotice", () => {
  const Harness = ({ value }: { value: string }) => <LocalTimeNotice field={useLocalTime(value)} label="the start" />;

  it("renders nothing for an ordinary time", () => {
    const { container } = render(<Harness value="2026-10-14T09:30:05" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the two occurrences, first selected, and switches", () => {
    render(<Harness value="2026-10-25T02:30:00" />);
    const first = screen.getByRole("button", { name: "first, UTC+02:00" });
    const second = screen.getByRole("button", { name: "second, UTC+01:00" });
    expect(first).toHaveAttribute("aria-pressed", "true");
    expect(second).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(second);
    expect(second).toHaveAttribute("aria-pressed", "true");
    expect(first).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the error for a skipped time", () => {
    render(<Harness value="2026-03-29T02:30" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Clocks go forward at this time, so 02:30 doesn't exist on 29 Mar.");
  });
});
