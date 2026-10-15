import { Suspense, lazy, useEffect, useState, type ComponentType } from "react";
import { createBrowserRouter, Outlet, RouterProvider, useNavigation, type RouteObject } from "react-router";
import { QueryClient, QueryClientProvider, useIsFetching, useIsMutating } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { ToastProvider } from "./toasts";
import { ActiveContextProvider } from "./context";
import { Shell } from "./Shell";
import { pages } from "./routePatterns";
import { Skeleton } from "@/components/states";
import { NotFound } from "./NotFound";
import { ApiError } from "@/api/errors";
import { useCrossTabSync } from "@/api/sync";
import { setPageTitle } from "./title";
import { LiveTitle } from "./LiveTitle";
import { CommandPalette } from "./CommandPalette";
import { OfflineSync } from "./OfflineSync";
import { MAX_AGE, persistOptions } from "./persist";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        /* Revisiting a page shows the last data instantly and refreshes
           behind it; 30 s keeps tab-switching from refetching everything. */
        staleTime: 30_000,
        /* As long as the saved copy lives (persist.ts), or it would be
           collected before it could be saved. */
        gcTime: MAX_AGE,
        refetchOnWindowFocus: true,
        retry: (count, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return count < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

function ProgressBar() {
  const navigation = useNavigation();
  const fetching = useIsFetching();
  const mutating = useIsMutating();
  if (navigation.state === "idle" && !mutating && !fetching) return null;
  return <div className="route-progress" aria-hidden="true" />;
}

function Layout() {
  useCrossTabSync();
  return (
    <ActiveContextProvider>
      <ProgressBar />
      <LiveTitle />
      <CommandPalette />
      <OfflineSync />
      <Shell>
        <Suspense fallback={<Skeleton lines={5} />}>
          <Outlet />
        </Suspense>
      </Shell>
    </ActiveContextProvider>
  );
}

function titled(Component: ComponentType, title: string) {
  return function TitledPage() {
    useEffect(() => setPageTitle(title), []);
    return <Component />;
  };
}

export function buildRoutes(): RouteObject[] {
  return [
    {
      element: <Layout />,
      children: [
        ...pages.map((page) => {
          const Page = lazy(page.load);
          const Titled = titled(Page, page.title);
          return { path: page.path, element: <Titled /> };
        }),
        { path: "*", element: <NotFound /> },
      ],
    },
  ];
}

export function App({ queryClient: provided }: { queryClient?: QueryClient }) {
  const [queryClient] = useState(() => provided ?? makeQueryClient());
  const [router] = useState(() => createBrowserRouter(buildRoutes()));
  /* Tests pass their own client and skip the device cache. */
  const [persist] = useState(() => (provided ? null : persistOptions()));
  const tree = (
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>
  );
  return persist ? (
    <PersistQueryClientProvider client={queryClient} persistOptions={persist}>
      {tree}
    </PersistQueryClientProvider>
  ) : (
    <QueryClientProvider client={queryClient}>{tree}</QueryClientProvider>
  );
}
