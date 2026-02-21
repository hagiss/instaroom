"use client";

import { useTranslations } from "next-intl";
import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useLocalJobs } from "@/hooks/use-local-jobs";

export function RecentJobsBanner() {
  const t = useTranslations("home.recentJobs");
  const { getLatest } = useLocalJobs();
  const latest = getLatest();

  if (!latest) return null;

  const href =
    latest.status === "completed" && latest.roomId
      ? `/r/${latest.username}`
      : `/status/${latest.jobId}`;

  const linkText =
    latest.status === "completed" ? t("viewRoom") : t("checkStatus");

  return (
    <motion.div
      className="glass w-full rounded-xl p-4"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.4 }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("title")}</p>
          <p className="truncate text-sm text-muted-foreground">
            @{latest.username}
          </p>
        </div>
        <Link
          href={href}
          className="flex shrink-0 items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          {linkText}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </motion.div>
  );
}
