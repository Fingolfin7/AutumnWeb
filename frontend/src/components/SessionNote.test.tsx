import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JournalDensityControl, SessionNote } from "./SessionNote";

beforeEach(() => {
  localStorage.clear();
  const Observer = class { observe() {} disconnect() {} };
  vi.stubGlobal("ResizeObserver", Observer);
  vi.stubGlobal("IntersectionObserver", Observer);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});
afterEach(() => vi.unstubAllGlobals());

it("keeps the whole journal by default and remembers preview density without changing the note", async () => {
  const user = userEvent.setup();
  const text = "First reflection.\n\nA second paragraph.\n\nThe final thought.";
  const view = render(<><JournalDensityControl /><SessionNote text={text} /></>);
  expect(view.container.querySelectorAll(".session-note-body p")).toHaveLength(3);
  expect(view.container.querySelector(".session-note")).not.toHaveClass("is-compact");
  await user.click(screen.getByRole("radio", { name: "2-line preview" }));
  expect(localStorage.getItem("autumn:journal-density")).toBe("preview");
  expect(view.container.querySelector(".session-note")).toHaveClass("is-compact");
  expect(view.container.querySelectorAll(".session-note-body p")).toHaveLength(3);
  view.unmount();
  const reopened = render(<SessionNote text={text} />);
  expect(reopened.container.querySelector(".session-note")).toHaveClass("is-compact");
  await user.click(screen.getByRole("button", { name: "Open note" }));
  expect(reopened.container.querySelector(".session-note")).toHaveClass("is-open");
  expect(screen.getByText("The final thought.")).toBeVisible();
});
