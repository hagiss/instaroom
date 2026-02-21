"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { motion, AnimatePresence } from "motion/react";
import { Loader2 } from "lucide-react";
import { ViewerControls } from "./viewer-controls";
import type { ViewerData } from "@/lib/types";

const SplatCanvas = dynamic(
  () =>
    import("./splat-canvas").then((mod) => ({ default: mod.SplatCanvas })),
  { ssr: false },
);

interface RoomViewerProps {
  viewerData: ViewerData;
}

export function RoomViewer({ viewerData }: RoomViewerProps) {
  const t = useTranslations("room.viewer");
  const [loaded, setLoaded] = useState(false);

  return (
    <div className="relative h-full w-full overflow-hidden rounded-2xl border border-white/[0.08]">
      <AnimatePresence>
        {!loaded && (
          <motion.div
            className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-background"
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4 }}
          >
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">{t("loading")}</p>
          </motion.div>
        )}
      </AnimatePresence>

      <SplatCanvas viewerData={viewerData} onLoaded={() => setLoaded(true)} />

      {loaded && <ViewerControls />}
    </div>
  );
}
