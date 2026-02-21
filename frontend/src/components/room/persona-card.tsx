"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown } from "lucide-react";

interface PersonaCardProps {
  summary: string;
}

export function PersonaCard({ summary }: PersonaCardProps) {
  const t = useTranslations("room.persona");
  const [expanded, setExpanded] = useState(false);

  const isLong = summary.length > 150;
  const displayText = isLong && !expanded ? summary.slice(0, 150) + "..." : summary;

  return (
    <div className="glass rounded-xl p-4">
      <h3 className="mb-2 text-sm font-semibold text-muted-foreground">
        {t("title")}
      </h3>
      <AnimatePresence mode="wait">
        <motion.p
          key={expanded ? "full" : "short"}
          className="text-sm leading-relaxed"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {displayText}
        </motion.p>
      </AnimatePresence>
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-2 flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? t("showLess") : t("showMore")}
          <ChevronDown
            className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`}
          />
        </button>
      )}
    </div>
  );
}
