import { expect, it } from "vitest";
import type { QueuedOp } from "@/lib/offlineQueue";
import { pendingSessions } from "./api";

it("lists a session logged offline as a row, with its note, length and subprojects", () => {
  const op = {
    kind: "session",
    key: "k",
    queuedAt: "2026-11-14T10:00:00.000Z",
    body: {
      uuid: "1b6d8a54-0c7e-4e2a-9a52-0d6b1f3f7c11",
      project_id: -7,
      start: "2026-11-14T08:00:00Z",
      end: "2026-11-14T08:45:00Z",
      note: "Scales, then the nocturne.",
      subproject_ids: [3, -9],
    },
    display: { projectName: "Piano Practice", subprojects: [{ id: 3, name: "Scales" }, { id: -9, name: "Repertoire" }] },
  } as QueuedOp;
  const [row] = pendingSessions([op, { ...op, kind: "start" } as unknown as QueuedOp]);
  expect(row).toMatchObject({
    pending_sync: true,
    project: { id: -7, name: "Piano Practice" },
    duration_minutes: 45,
    note: "Scales, then the nocturne.",
    subproject_allocations: [
      { subproject_id: 3, name: "Scales", allocation_bp: 5000 },
      { subproject_id: -9, name: "Repertoire", allocation_bp: 5000 },
    ],
  });
  expect(row!.id).toBeLessThan(0);
});
