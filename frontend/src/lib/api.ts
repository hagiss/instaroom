import type { GenerateRequest, GenerateResponse, JobResponse, RoomResponse } from "./types";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetcher<T>(url: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { ...options?.headers as Record<string, string> };
  if (options?.body) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }

  return res.json();
}

export const api = {
  generate(data: GenerateRequest): Promise<GenerateResponse> {
    return fetcher("/api/generate", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getJob(jobId: string): Promise<JobResponse> {
    return fetcher(`/api/jobs/${jobId}`);
  },

  getRoom(roomId: string): Promise<RoomResponse> {
    return fetcher(`/api/rooms/${roomId}`);
  },

  getRoomByUsername(username: string): Promise<RoomResponse> {
    return fetcher(`/api/rooms/by-username/${username}`);
  },
};

export { ApiError };
