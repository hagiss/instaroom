import type { JobStatus } from "./types";

export const POLL_INTERVAL_MS = 3000;

export interface StageConfig {
  key: JobStatus;
  stageIndex: number;
  labelKey: string;
  descriptionKey: string;
  icon: string;
}

export const STAGES: StageConfig[] = [
  {
    key: "crawling",
    stageIndex: 0,
    labelKey: "status.stages.crawling.label",
    descriptionKey: "status.stages.crawling.description",
    icon: "Search",
  },
  {
    key: "analyzing",
    stageIndex: 1,
    labelKey: "status.stages.analyzing.label",
    descriptionKey: "status.stages.analyzing.description",
    icon: "ScanEye",
  },
  {
    key: "aggregating",
    stageIndex: 2,
    labelKey: "status.stages.aggregating.label",
    descriptionKey: "status.stages.aggregating.description",
    icon: "Layers",
  },
  {
    key: "prompting",
    stageIndex: 3,
    labelKey: "status.stages.prompting.label",
    descriptionKey: "status.stages.prompting.description",
    icon: "Wand2",
  },
  {
    key: "generating_image",
    stageIndex: 4,
    labelKey: "status.stages.generating_image.label",
    descriptionKey: "status.stages.generating_image.description",
    icon: "Image",
  },
  {
    key: "converting_3d",
    stageIndex: 5,
    labelKey: "status.stages.converting_3d.label",
    descriptionKey: "status.stages.converting_3d.description",
    icon: "Box",
  },
];

export const TERMINAL_STATUSES: JobStatus[] = ["completed", "failed"];

export const USERNAME_REGEX = /^[a-zA-Z0-9._]{1,30}$/;
