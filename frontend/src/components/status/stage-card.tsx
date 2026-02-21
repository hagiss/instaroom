"use client";

import { motion } from "motion/react";
import { Check, Search, ScanEye, Layers, Wand2, Image, Box } from "lucide-react";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Search,
  ScanEye,
  Layers,
  Wand2,
  Image,
  Box,
};

export type StageState = "pending" | "active" | "completed";

interface StageCardProps {
  icon: string;
  label: string;
  description: string;
  state: StageState;
  progress?: string | null;
  isLast?: boolean;
}

export function StageCard({
  icon,
  label,
  description,
  state,
  progress,
  isLast,
}: StageCardProps) {
  const Icon = ICON_MAP[icon] || Box;

  return (
    <div className="flex gap-3">
      {/* Timeline connector */}
      <div className="flex flex-col items-center">
        <div className="relative">
          {state === "completed" ? (
            <motion.div
              className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-400"
              initial={{ scale: 0.5 }}
              animate={{ scale: 1 }}
              transition={{ type: "spring", stiffness: 300, damping: 20 }}
            >
              <Check className="h-4 w-4" />
            </motion.div>
          ) : state === "active" ? (
            <div className="relative flex h-8 w-8 items-center justify-center">
              <motion.div
                className="absolute inset-0 rounded-full bg-primary/20"
                animate={{ scale: [1, 1.4, 1], opacity: [0.5, 0, 0.5] }}
                transition={{ duration: 2, repeat: Infinity }}
              />
              <div className="flex h-8 w-8 items-center justify-center rounded-full border border-primary/50 bg-primary/10 text-primary">
                <Icon className="h-4 w-4" />
              </div>
            </div>
          ) : (
            <div className="flex h-8 w-8 items-center justify-center rounded-full border border-white/[0.08] text-muted-foreground">
              <Icon className="h-4 w-4" />
            </div>
          )}
        </div>
        {!isLast && (
          <div className="relative h-full w-px min-h-[2rem]">
            <div className="absolute inset-0 bg-white/[0.08]" />
            {state === "completed" && (
              <motion.div
                className="absolute inset-0 bg-emerald-500/40"
                initial={{ scaleY: 0 }}
                animate={{ scaleY: 1 }}
                transition={{ duration: 0.3 }}
                style={{ transformOrigin: "top" }}
              />
            )}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="pb-6">
        <motion.div
          className={`rounded-xl px-3 py-2 transition-colors ${
            state === "active"
              ? "glass-strong glow"
              : state === "completed"
                ? "opacity-70"
                : "opacity-40"
          }`}
          layout
        >
          <p
            className={`text-sm font-medium ${
              state === "active"
                ? "text-primary"
                : state === "completed"
                  ? "text-emerald-400"
                  : "text-muted-foreground"
            }`}
          >
            {label}
          </p>
          <p className="text-xs text-muted-foreground">{description}</p>
          {state === "active" && progress && (
            <motion.p
              className="mt-1 text-xs text-primary/70"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              {progress}
            </motion.p>
          )}
        </motion.div>
      </div>
    </div>
  );
}
