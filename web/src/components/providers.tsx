"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { SyncWatcher } from "./sync-watcher";
import { ServiceWorker } from "./service-worker";

/**
 * Section 15b: *"TanStack Query v5 for server cache and optimistic corrections.
 * No Redux, no Zustand — server state plus URL params covers every screen."*
 * There is no store here and there is not going to be one.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Section 11: *"Nothing auto-refreshes — a moving dashboard is
            // unusable when someone is reading a figure aloud."* Both of these
            // default to true in TanStack Query and both would move a number
            // under a reader's finger.
            refetchOnWindowFocus: false,
            refetchInterval: false,
            staleTime: 30_000,
            retry: (failureCount, error) => {
              // Retrying while offline is how a phone flattens its battery in a
              // market. The outbox is the offline mechanism, not the retry.
              const status = (error as { status?: number }).status;
              if (status === 0 || status === 401 || status === 403) return false;
              return failureCount < 2;
            },
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <ServiceWorker />
      <SyncWatcher />
      {children}
    </QueryClientProvider>
  );
}
