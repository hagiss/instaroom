"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { motion } from "motion/react";
import { ArrowRight, Loader2, AtSign } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRouter } from "@/i18n/navigation";
import { useLocalJobs } from "@/hooks/use-local-jobs";
import { api } from "@/lib/api";
import { USERNAME_REGEX } from "@/lib/constants";

export function UsernameInput() {
  const t = useTranslations("home.input");
  const router = useRouter();
  const { saveJob } = useLocalJobs();

  const [username, setUsername] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const trimmed = username.trim().replace(/^@/, "");
    if (!trimmed) {
      setError(t("error.required"));
      return;
    }
    if (!USERNAME_REGEX.test(trimmed)) {
      setError(t("error.invalid"));
      return;
    }

    setError(null);
    setLoading(true);

    try {
      const res = await api.generate({ username: trimmed });

      saveJob({
        jobId: res.job_id,
        username: trimmed,
        status: res.room_id ? "completed" : "pending",
        roomId: res.room_id,
      });

      if (res.room_id) {
        router.push(`/r/${trimmed}`);
      } else {
        router.push(`/status/${res.job_id}`);
      }
    } catch {
      setError(t("error.failed"));
      setLoading(false);
    }
  }

  return (
    <motion.form
      onSubmit={handleSubmit}
      className="glass glow w-full rounded-2xl p-6"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.2, ease: "easeOut" }}
    >
      <div className="flex flex-col gap-4">
        <Label htmlFor="username" className="text-sm text-muted-foreground">
          {t("label")}
        </Label>
        <div className="relative">
          <AtSign className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="username"
            type="text"
            placeholder={t("placeholder")}
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
              setError(null);
            }}
            className="h-12 bg-white/[0.03] pl-10 text-base"
            disabled={loading}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </div>
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        <Button
          type="submit"
          size="lg"
          disabled={loading}
          className="h-12 w-full gap-2 text-base font-semibold"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("loading")}
            </>
          ) : (
            <>
              {t("button")}
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </motion.form>
  );
}
