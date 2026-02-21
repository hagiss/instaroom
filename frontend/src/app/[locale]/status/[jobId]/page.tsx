"use client";

import { use, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { motion, AnimatePresence } from "motion/react";
import { Sparkles } from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { useJobPolling } from "@/hooks/use-job-polling";
import { useLocalJobs } from "@/hooks/use-local-jobs";
import { StageProgress } from "@/components/status/stage-progress";
import { ErrorState } from "@/components/status/error-state";

export default function StatusPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = use(params);
  const t = useTranslations("status");
  const router = useRouter();
  const { job, error } = useJobPolling(jobId);
  const { saveJob } = useLocalJobs();
  const hasRedirected = useRef(false);

  useEffect(() => {
    if (
      job?.status === "completed" &&
      job.result &&
      job.username &&
      !hasRedirected.current
    ) {
      hasRedirected.current = true;
      saveJob({
        jobId: job.job_id,
        username: job.username,
        status: "completed",
        roomId: job.result.room_id,
      });

      const timer = setTimeout(() => {
        router.push(`/r/${job.username}`);
      }, 1500);

      return () => clearTimeout(timer);
    }
  }, [job, router, saveJob]);

  return (
    <div className="gradient-bg flex min-h-dvh flex-col items-center px-4 pt-24">
      <div className="mx-auto w-full max-w-md">
        <motion.div
          className="mb-8 text-center"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h1 className="text-2xl font-bold">{t("title")}</h1>
          {job?.username && (
            <p className="mt-2 text-sm text-muted-foreground">
              {t("subtitle", { username: job.username })}
            </p>
          )}
        </motion.div>

        {error && !job && (
          <ErrorState message={error} />
        )}

        {job?.status === "failed" && job.error && (
          <ErrorState
            message={job.error.message}
            username={job.username}
          />
        )}

        {job && job.status !== "failed" && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            <StageProgress job={job} />

            <AnimatePresence>
              {job.status === "completed" && (
                <motion.div
                  className="mt-6 flex flex-col items-center gap-2 text-center"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ type: "spring", stiffness: 200 }}
                >
                  <Sparkles className="h-6 w-6 text-primary" />
                  <p className="text-lg font-semibold text-primary glow-text">
                    {t("completed")}
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </div>
    </div>
  );
}
