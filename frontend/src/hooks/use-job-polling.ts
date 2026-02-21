"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { POLL_INTERVAL_MS, TERMINAL_STATUSES } from "@/lib/constants";
import type { JobResponse } from "@/lib/types";

export function useJobPolling(jobId: string) {
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    let mounted = true;

    async function poll() {
      try {
        const data = await api.getJob(jobId);
        if (!mounted) return;

        setJob(data);
        setError(null);

        if (TERMINAL_STATUSES.includes(data.status)) {
          stop();
        }
      } catch (err) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : "Failed to fetch status");
      }
    }

    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      mounted = false;
      stop();
    };
  }, [jobId, stop]);

  return { job, error, stop };
}
