"use client";

import { useTranslations } from "next-intl";
import { motion } from "motion/react";
import { AlertCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRouter } from "@/i18n/navigation";

interface ErrorStateProps {
  message: string;
  username?: string | null;
}

export function ErrorState({ message, username }: ErrorStateProps) {
  const t = useTranslations("status.failed");
  const router = useRouter();

  function handleRetry() {
    router.push("/");
  }

  return (
    <motion.div
      className="glass flex flex-col items-center gap-4 rounded-2xl p-6 text-center"
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
        <AlertCircle className="h-6 w-6 text-destructive" />
      </div>
      <div>
        <h3 className="text-lg font-semibold">{t("title")}</h3>
        <p className="mt-1 text-sm text-muted-foreground">{message}</p>
        {username && (
          <p className="mt-1 text-xs text-muted-foreground">@{username}</p>
        )}
      </div>
      <Button onClick={handleRetry} variant="outline" className="gap-2">
        <RotateCcw className="h-4 w-4" />
        {t("retry")}
      </Button>
    </motion.div>
  );
}
