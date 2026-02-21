"use client";

import { useTranslations } from "next-intl";
import { motion } from "motion/react";
import { Home } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";

export default function RoomNotFound() {
  const t = useTranslations("room.notFound");

  return (
    <div className="gradient-bg flex min-h-dvh flex-col items-center justify-center px-4 pt-14">
      <motion.div
        className="glass flex max-w-md flex-col items-center gap-4 rounded-2xl p-8 text-center"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="text-6xl">🏠</div>
        <h1 className="text-2xl font-bold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("description")}</p>
        <Button asChild className="gap-2">
          <Link href="/">
            <Home className="h-4 w-4" />
            {t("goHome")}
          </Link>
        </Button>
      </motion.div>
    </div>
  );
}
