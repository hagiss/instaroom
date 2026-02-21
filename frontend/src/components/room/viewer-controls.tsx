"use client";

import { useState, useCallback, useEffect } from "react";
import { useTranslations } from "next-intl";
import { RotateCcw, Maximize, Minimize } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ViewerControls() {
  const t = useTranslations("room.viewer");
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    function handleChange() {
      setIsFullscreen(!!document.fullscreenElement);
    }
    document.addEventListener("fullscreenchange", handleChange);
    return () => document.removeEventListener("fullscreenchange", handleChange);
  }, []);

  const handleReset = useCallback(() => {
    const container = document.querySelector<
      HTMLDivElement & { resetView?: () => void }
    >("[data-splat-container]");
    container?.resetView?.();
  }, []);

  const handleFullscreen = useCallback(async () => {
    const viewer = document.querySelector("[data-viewer]");
    if (!viewer) return;

    if (!document.fullscreenElement) {
      await viewer.requestFullscreen().catch(() => {});
    } else {
      await document.exitFullscreen().catch(() => {});
    }
  }, []);

  return (
    <div className="absolute bottom-4 right-4 z-20 flex gap-2">
      <Button
        variant="outline"
        size="icon"
        onClick={handleReset}
        className="glass h-9 w-9"
        aria-label={t("reset")}
      >
        <RotateCcw className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="icon"
        onClick={handleFullscreen}
        className="glass h-9 w-9"
        aria-label={isFullscreen ? t("exitFullscreen") : t("fullscreen")}
      >
        {isFullscreen ? (
          <Minimize className="h-4 w-4" />
        ) : (
          <Maximize className="h-4 w-4" />
        )}
      </Button>
    </div>
  );
}
