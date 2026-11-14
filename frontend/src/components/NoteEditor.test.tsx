import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NoteEditor, resolveRecognitionLanguage } from "./NoteEditor";

function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <NoteEditor value={value} onChange={setValue} />;
}

const box = () => screen.getByRole("textbox") as HTMLTextAreaElement;

afterEach(() => {
  window.sessionStorage.clear();
  vi.restoreAllMocks();
});

it("bold wraps the selection and leaves the caret after it", async () => {
  const user = userEvent.setup();
  render(<Harness initial="hello world" />);
  box().setSelectionRange(6, 11);
  await user.click(screen.getByRole("button", { name: "Bold" }));
  expect(box().value).toBe("hello **world**");
});

it("with nothing selected the caret lands between the markers", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Italic" }));
  await user.keyboard("x");
  expect(box().value).toBe("*x*");
});

it("Ctrl+B is the bold shortcut", async () => {
  const user = userEvent.setup();
  render(<Harness initial="a" />);
  box().setSelectionRange(0, 1);
  box().focus();
  await user.keyboard("{Control>}b{/Control}");
  expect(box().value).toBe("**a**");
});

it("link asks for a URL and inserts a markdown link around the selection", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "prompt").mockReturnValue("https://example.com");
  render(<Harness initial="see docs" />);
  box().setSelectionRange(4, 8);
  await user.click(screen.getByRole("button", { name: "Link" }));
  expect(box().value).toBe("see [docs](https://example.com)");
});

it("link does nothing when the prompt is cancelled", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "prompt").mockReturnValue(null);
  render(<Harness initial="x" />);
  await user.click(screen.getByRole("button", { name: "Link" }));
  expect(box().value).toBe("x");
});


it("disables dictation where the browser has no speech recognition", () => {
  render(<Harness />);
  expect(screen.getByRole("button", { name: /Unavailable/ })).toBeDisabled();
  expect(screen.getByText("Dictation unavailable in this browser.")).toBeInTheDocument();
});

describe("resolveRecognitionLanguage", () => {
  it("expands bare language codes and keeps regional ones", () => {
    expect(resolveRecognitionLanguage(null, "en")).toBe("en-US");
    expect(resolveRecognitionLanguage(null, "fr")).toBe("fr-FR");
    expect(resolveRecognitionLanguage(null, "pt-BR")).toBe("pt-BR");
  });
});
