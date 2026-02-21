"use client";

import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";

export function Footer() {
  const t = useTranslations("footer");

  return (
    <footer className="border-t border-white/[0.06] py-6">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-2 px-4 text-center text-sm text-muted-foreground">
        <p>{t("tagline")}</p>
        <p className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5" />
          {t("madeWith")}
        </p>
      </div>
    </footer>
  );
}
