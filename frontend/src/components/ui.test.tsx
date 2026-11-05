import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { DateInput, Input, SegmentedControl } from "./ui";

it("keeps reminder presets inside the calendar and respects the date boundary", () => {
  const onChange = vi.fn();
  render(<DateInput today="2026-11-05" min="2026-11-06" value="2026-11-06" presets="future" onValueChange={onChange} />);
  expect(screen.queryByRole("button", { name: "Tomorrow" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Choose date" }));
  expect(screen.getByRole("button", { name: "Today" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next week" }));
  expect(onChange).toHaveBeenCalledWith("2026-11-12");
});

it("edits whole minutes and lets an already selected Custom range reopen", () => {
  function Fields() {
    const [time, setTime] = useState("09:15");
    return <Input aria-label="Reminder time" type="time" value={time} onChange={event => setTime(event.target.value)} />;
  }
  const reselect = vi.fn();
  render(<><Fields /><SegmentedControl label="Range" value="custom" options={[{ value: "custom", label: "Custom" }]} onChange={vi.fn()} onReselect={reselect} /></>);
  fireEvent.click(screen.getByRole("button", { name: "Choose time" }));
  fireEvent.change(screen.getByLabelText("Minute"), { target: { value: "30" } });
  expect(screen.getByLabelText("Reminder time")).toHaveValue("09:30");
  fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
  expect(reselect).toHaveBeenCalledWith("custom");
});
