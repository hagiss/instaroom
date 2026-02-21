"use client";

import { useTranslations } from "next-intl";
import { motion } from "motion/react";

export function HeroSection() {
  const t = useTranslations("home.hero");

  return (
    <motion.div
      className="flex flex-col items-center gap-4 text-center"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: "easeOut" }}
    >
      <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
        {t("title")}
        <br />
        <span className="glow-text text-primary">{t("titleAccent")}</span>
      </h1>
      <p className="max-w-md text-base text-muted-foreground sm:text-lg">
        {t("subtitle")}
      </p>
    </motion.div>
  );
}
