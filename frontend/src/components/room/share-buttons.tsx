"use client";

import { useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Share2, Copy, Check, Twitter } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ShareButtonsProps {
  username: string;
  url: string;
}

export function ShareButtons({ username, url }: ShareButtonsProps) {
  const t = useTranslations("room.share");
  const [copied, setCopied] = useState(false);
  const [canShare] = useState(
    () => typeof navigator !== "undefined" && "share" in navigator,
  );

  const handleNativeShare = useCallback(async () => {
    try {
      await navigator.share({
        title: `${username}'s Room — Instaroom`,
        url,
      });
    } catch {
      // User cancelled
    }
  }, [username, url]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API not available
    }
  }, [url]);

  const handleTwitter = useCallback(() => {
    const text = encodeURIComponent(
      `Check out ${username}'s AI-generated 3D room!`,
    );
    const encodedUrl = encodeURIComponent(url);
    window.open(
      `https://twitter.com/intent/tweet?text=${text}&url=${encodedUrl}`,
      "_blank",
      "noopener,noreferrer",
    );
  }, [username, url]);

  return (
    <div className="glass rounded-xl p-4">
      <h3 className="mb-3 text-sm font-semibold text-muted-foreground">
        {t("title")}
      </h3>
      <div className="flex flex-wrap gap-2">
        {canShare && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleNativeShare}
            className="gap-1.5"
          >
            <Share2 className="h-3.5 w-3.5" />
            {t("native")}
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={handleCopy}
          className="gap-1.5"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-emerald-400" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
          {copied ? t("copied") : t("copy")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleTwitter}
          className="gap-1.5"
        >
          <Twitter className="h-3.5 w-3.5" />
          {t("twitter")}
        </Button>
      </div>
    </div>
  );
}
