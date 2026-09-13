"use client";

import { useEffect } from "react";

/** Marks the document once React has hydrated, so the browser smoke test can prove client code ran on every route. */
export function HydrationMark() {
  useEffect(() => {
    document.documentElement.dataset.hydrated = "true";
  }, []);
  return null;
}
