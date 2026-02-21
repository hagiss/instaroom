export interface GenerateRequest {
  username: string;
}

export interface GenerateResponse {
  job_id: string;
  existing: boolean;
  room_id?: string;
}

export interface ViewerData {
  splat_url: string;
  collider_url: string;
  panorama_url: string;
  camera_position: [number, number, number];
  camera_target: [number, number, number];
}

export interface JobResult {
  room_id: string;
  room_url: string;
  screenshot_url: string;
  persona_summary: string;
  viewer_data: ViewerData;
}

export interface JobError {
  message: string;
  stage: number;
}

export type JobStatus =
  | "crawling"
  | "analyzing"
  | "aggregating"
  | "prompting"
  | "generating_image"
  | "converting_3d"
  | "completed"
  | "failed";

export interface JobResponse {
  job_id: string;
  username: string | null;
  status: JobStatus;
  stage: number | null;
  progress: string | null;
  result: JobResult | null;
  error: JobError | null;
}

export interface RoomResponse {
  room_id: string;
  username: string;
  persona_summary: string;
  screenshot_url: string;
  viewer_data: ViewerData;
  created_at: string;
}
