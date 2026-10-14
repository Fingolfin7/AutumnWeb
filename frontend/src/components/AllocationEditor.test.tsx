import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AllocationEditor } from "./AllocationEditor";
import type { AllocationItem, AllocationWrite } from "@/lib/allocation";

const three: AllocationItem[] = [
  { id: 1, name: "Grammar" },
  { id: 2, name: "Listening" },
  { id: 3, name: "Speaking" },
];

function setup(items: AllocationItem[], props: { collapsible?: boolean } = {}) {
  const onChange = vi.fn<(a: AllocationWrite[] | null) => void>();
  const view = render(<AllocationEditor items={items} onChange={onChange} {...props} />);
  const last = () => onChange.mock.calls.at(-1)![0];
  return { onChange, last, view };
}

it("renders nothing for fewer than two subprojects and reports null", () => {
  const { view, last } = setup([three[0]!]);
  expect(view.container).toBeEmptyDOMElement();
  expect(last()).toBeNull();
});

it("starts even and reports basis points summing to 10000", () => {
  const { last } = setup(three);
  expect(last()).toEqual([
    { subproject_id: 1, allocation_bp: 3400 },
    { subproject_id: 2, allocation_bp: 3300 },
    { subproject_id: 3, allocation_bp: 3300 },
  ]);
  expect(screen.getByText("Even split")).toBeInTheDocument();
  expect(screen.getByText("Fully allocated")).toBeInTheDocument();
});

it("starts from stored allocations", () => {
  const { last } = setup([
    { id: 1, name: "A", bp: 7000 },
    { id: 2, name: "B", bp: 3000 },
  ]);
  expect(last()).toEqual([
    { subproject_id: 1, allocation_bp: 7000 },
    { subproject_id: 2, allocation_bp: 3000 },
  ]);
  expect(screen.getByText("Custom split")).toBeInTheDocument();
});

it("typing a percent applies on Enter and rebalances the others", async () => {
  const user = userEvent.setup();
  const { last } = setup(three);
  const input = screen.getByLabelText("Grammar percent");
  await user.clear(input);
  await user.type(input, "50{Enter}");
  expect(last()).toEqual([
    { subproject_id: 1, allocation_bp: 5000 },
    { subproject_id: 2, allocation_bp: 2500 },
    { subproject_id: 3, allocation_bp: 2500 },
  ]);
});

it("a locked row keeps its value and can't be edited", async () => {
  const user = userEvent.setup();
  const { last } = setup(three);
  await user.click(screen.getByRole("button", { name: "Lock Speaking" }));
  expect(screen.getByLabelText("Speaking percent")).toBeDisabled();
  await user.clear(screen.getByLabelText("Grammar percent"));
  await user.type(screen.getByLabelText("Grammar percent"), "60{Enter}");
  expect(last()!.find((a) => a.subproject_id === 3)!.allocation_bp).toBe(3300);
  expect(last()!.find((a) => a.subproject_id === 1)!.allocation_bp).toBe(6000);
});

it("Distribute evenly resets values and releases locks", async () => {
  const user = userEvent.setup();
  const { last } = setup(three);
  await user.click(screen.getByRole("button", { name: "Lock Speaking" }));
  await user.clear(screen.getByLabelText("Grammar percent"));
  await user.type(screen.getByLabelText("Grammar percent"), "60{Enter}");
  await user.click(screen.getByRole("button", { name: /Distribute evenly/ }));
  expect(last()!.map((a) => a.allocation_bp)).toEqual([3400, 3300, 3300]);
  expect(screen.getByRole("button", { name: "Lock Speaking" })).toHaveAttribute("aria-pressed", "false");
});

it("resets to an even split when the selected set changes", () => {
  const onChange = vi.fn<(a: AllocationWrite[] | null) => void>();
  const stored: AllocationItem[] = [
    { id: 1, name: "A", bp: 7000 },
    { id: 2, name: "B", bp: 3000 },
  ];
  const { rerender } = render(<AllocationEditor items={stored} onChange={onChange} />);
  rerender(<AllocationEditor items={[...stored, { id: 3, name: "C", bp: 0 }]} onChange={onChange} />);
  expect(onChange.mock.calls.at(-1)![0]!.map((a) => a.allocation_bp)).toEqual([3400, 3300, 3300]);
});

it("collapsible mode hides the body until the header is opened", async () => {
  const user = userEvent.setup();
  setup(three, { collapsible: true });
  const head = screen.getByRole("button", { name: /Time split/ });
  expect(head).toHaveAttribute("aria-expanded", "false");
  expect(head).toHaveTextContent("Even split · 34 / 33 / 33");
  await user.click(head);
  expect(head).toHaveAttribute("aria-expanded", "true");
});
