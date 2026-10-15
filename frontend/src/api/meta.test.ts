const GET = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ api: { GET }, unwrap: (promise: Promise<unknown>) => promise }));

import { fetchAllProjects } from "./meta";

beforeEach(() => {
  GET.mockReset();
  GET.mockResolvedValue({ projects: [], total: 0 });
});

it("lists by name unless the caller picks another order, and passes its filters through", async () => {
  await fetchAllProjects();
  expect(GET.mock.calls[0]![1].params.query).toMatchObject({ ordering: "name", limit: 200, offset: 0 });
  await fetchAllProjects({ ordering: "last_activity", search: "oak", start_date: "2026-10-01" });
  expect(GET.mock.calls[1]![1].params.query).toMatchObject({ ordering: "last_activity", search: "oak", start_date: "2026-10-01" });
});
