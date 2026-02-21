"use client";

import { useCallback, useSyncExternalStore } from "react";

interface LocalJob {
  jobId: string;
  username: string;
  status: "pending" | "completed";
  roomId?: string;
  createdAt: number;
}

const STORAGE_KEY = "instaroom_jobs";

function getSnapshot(): LocalJob[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function getServerSnapshot(): LocalJob[] {
  return [];
}

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

export function useLocalJobs() {
  const jobs = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const saveJob = useCallback(
    (job: Omit<LocalJob, "createdAt">) => {
      const current = getSnapshot();
      const existing = current.findIndex((j) => j.username === job.username);
      const newJob: LocalJob = { ...job, createdAt: Date.now() };

      let updated: LocalJob[];
      if (existing >= 0) {
        updated = [...current];
        updated[existing] = newJob;
      } else {
        updated = [newJob, ...current].slice(0, 10);
      }

      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      window.dispatchEvent(new Event("storage"));
    },
    [],
  );

  const getLatest = useCallback((): LocalJob | null => {
    return jobs[0] ?? null;
  }, [jobs]);

  return { jobs, saveJob, getLatest };
}
