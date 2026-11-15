import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createMemoryRouter, RouterProvider } from "react-router";
import { QueryClient } from "@tanstack/react-query";
import { App, buildRoutes } from "./App";

vi.mock("./routePatterns", async (original) => ({
  ...(await original<typeof import("./routePatterns")>()),
  pages: [
    { path: "/", title: "Home", load: () => Promise.reject(new TypeError("Failed to fetch dynamically imported module")) },
    { path: "/broken/", title: "Broken", load: async () => ({ default: () => { throw new Error("boom"); } }) },
  ],
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("says a page isn't saved on this device when its code can't be fetched offline, inside the shell", async () => {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  render(<App queryClient={new QueryClient()} />);
  expect(await screen.findByRole("heading", { name: "This page isn't saved on this device yet" })).toBeInTheDocument();
  expect(screen.queryByText(/Unexpected Application Error/)).toBeNull();
  expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
});

it("offers a reload when a page crashes", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(<RouterProvider router={createMemoryRouter(buildRoutes().map((route) => ({ ...route, element: undefined })), { initialEntries: ["/broken/"] })} />);
  expect(await screen.findByRole("heading", { name: "Something went wrong on this page" })).toBeInTheDocument();
  expect(screen.getByText("boom")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
});
