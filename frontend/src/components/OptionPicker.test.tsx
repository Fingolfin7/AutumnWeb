import { fireEvent, render, screen } from "@testing-library/react";
import { OptionPicker } from "./OptionPicker";

it("opens a searchable picker and closes it with Escape", () => {
  const onChange = vi.fn();
  render(<OptionPicker label="Projects" options={[{ id: 1, label: "Garden" }, { id: 2, label: "Reading" }]} selected={[]} onChange={onChange} />);
  const summary = screen.getByText("Choose projects");
  fireEvent.click(summary);
  const search = screen.getByRole("textbox", { name: "Search projects" });
  fireEvent.change(search, { target: { value: "garden" } });
  fireEvent.click(screen.getByRole("button", { name: "Garden" }));
  expect(onChange).toHaveBeenCalledWith([1]);
  expect(screen.queryByRole("button", { name: "Reading" })).toBeNull();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(summary.closest("details")?.open).toBe(false);
  expect(document.activeElement).toBe(summary);
});
