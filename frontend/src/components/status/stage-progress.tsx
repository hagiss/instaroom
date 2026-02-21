"use client";

import { useTranslations } from "next-intl";
import { STAGES } from "@/lib/constants";
import type { JobResponse } from "@/lib/types";
import { StageCard, type StageState } from "./stage-card";

interface StageProgressProps {
  job: JobResponse;
}

function getStageState(
  stageIndex: number,
  currentStage: number | null,
  status: string,
): StageState {
  if (status === "completed") return "completed";
  if (currentStage === null) return stageIndex === 0 ? "active" : "pending";
  if (stageIndex < currentStage) return "completed";
  if (stageIndex === currentStage) return "active";
  return "pending";
}

export function StageProgress({ job }: StageProgressProps) {
  const t = useTranslations();

  return (
    <div className="flex flex-col">
      {STAGES.map((stage, idx) => (
        <StageCard
          key={stage.key}
          icon={stage.icon}
          label={t(stage.labelKey)}
          description={t(stage.descriptionKey)}
          state={getStageState(stage.stageIndex, job.stage, job.status)}
          progress={
            getStageState(stage.stageIndex, job.stage, job.status) === "active"
              ? job.progress
              : null
          }
          isLast={idx === STAGES.length - 1}
        />
      ))}
    </div>
  );
}
