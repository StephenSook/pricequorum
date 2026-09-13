"use client";

import { useEffect } from "react";

/** Marks the document once React has hydrated, so the browser smoke test can prove client code ran on every route. */
export function HydrationMark() {
  useEffect(() => {
    document.documentElement.dataset.hydrated = "true";
  }, []);
  return null;
}

/**
 * Marks the document once a route's own client component has mounted. The shared root marker
 * cannot prove that, because it lives in a different JavaScript chunk from the route.
 */
export function useRouteReady(route: string) {
  useEffect(() => {
    document.documentElement.dataset.routeReady = route;
  }, [route]);
}
