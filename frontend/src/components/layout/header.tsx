"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Box } from "lucide-react";
import { LocaleSwitcher } from "./locale-switcher";

export function Header() {
  const t = useTranslations("header");

  return (
    <header className="fixed top-0 z-50 w-full border-b border-white/[0.06] bg-background/60 backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2">
          <Box className="h-5 w-5 text-primary" />
          <span className="text-lg font-semibold tracking-tight">
            {t("title")}
          </span>
        </Link>
        <LocaleSwitcher />
      </div>
    </header>
  );
}
