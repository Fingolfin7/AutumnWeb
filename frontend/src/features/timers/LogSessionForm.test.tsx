import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { Project } from "@/api/types";
import type { LogSessionInput } from "@/features/sessions/api";
import { LogSessionForm } from "./LogSessionForm";
import type { ProjectPick } from "./ProjectPick";

const mutate = vi.hoisted(() => vi.fn());
vi.mock("@/features/sessions/api", () => ({ useLogSession: () => ({ mutate, isPending: false }) }));
vi.mock("@/app/toasts", () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));
vi.mock("@/api/meta", () => ({ useAllProjects: () => ({ data: [] }), useQueuedOps: () => [], withPendingProjects: (projects: unknown[]) => projects }));

const subs = [
  { id: 8, name: "Scales" },
  { id: 9, name: "Repertoire" },
];

function renderForm(project: Project | null) {
  const pick = {
    project,
    selected: project ? [8, 9] : [],
    setSelected: vi.fn(),
    subprojects: { data: subs, isPending: false, isError: false },
    subs,
    chosen: project ? subs : [],
    pickProject: vi.fn(),
  } as unknown as ProjectPick;
  return render(
    <MemoryRouter>
      <LogSessionForm pick={pick} autoFocus={false} />
    </MemoryRouter>,
  );
}

beforeEach(() => mutate.mockReset());

it("asks for a project and an end after the start before sending", () => {
  renderForm(null);
  fireEvent.change(screen.getByLabelText("End time"), { target: { value: "2026-03-02T09:00" } });
  fireEvent.change(screen.getByLabelText("Start time"), { target: { value: "2026-03-02T10:00" } });
  fireEvent.click(screen.getByRole("button", { name: /Log session/ }));
  expect(screen.getByText("Choose a project.")).toBeInTheDocument();
  expect(screen.getByText("The end must be after the start.")).toBeInTheDocument();
  expect(mutate).not.toHaveBeenCalled();
});

it("sends one uuid per form, the instants, the note and the split", () => {
  renderForm({ id: 3, name: "Piano Practice" } as Project);
  /* Defaults: an hour ending now. */
  expect(screen.getByRole("status")).toHaveTextContent("1 hour logged");
  fireEvent.click(screen.getByRole("button", { name: "30m" }));
  expect(screen.getByRole("status")).toHaveTextContent("30 minutes logged");
  fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Scales.\n\nThen the nocturne." } });
  fireEvent.click(screen.getByRole("button", { name: /Log session/ }));
  fireEvent.click(screen.getByRole("button", { name: /Log session/ }));

  expect(mutate).toHaveBeenCalledTimes(2);
  const [first, second] = mutate.mock.calls.map(([input]) => input as LogSessionInput);
  expect(first!.uuid).toMatch(/^[0-9a-f-]{36}$/);
  expect(second!.uuid).toBe(first!.uuid);
  expect(first).toMatchObject({
    project_id: 3,
    note: "Scales.\n\nThen the nocturne.",
    subproject_allocations: [
      { subproject_id: 8, allocation_bp: 5000 },
      { subproject_id: 9, allocation_bp: 5000 },
    ],
  });
  expect(Date.parse(first!.end) - Date.parse(first!.start)).toBe(30 * 60_000);
  expect(JSON.parse(JSON.stringify(first))).toEqual(first);
});
