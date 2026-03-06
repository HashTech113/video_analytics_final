import { API_BASE_URL } from "@/config/env";
import { requestBlob, requestJson, toBackendAssetUrl } from "@/lib/http";

interface ApiResponse<T> {
  data: T;
  success: boolean;
  message?: string;
}

interface UploadResponse {
  message: string;
  job_id: string;
  status: "processing";
  frame_stride: number;
  use_cases?: string[];
}

interface UploadJobStatus {
  job_id: string;
  record_id: string;
  video_name: string;
  status: "processing" | "completed" | "failed";
  progress: number;
  frame_stride?: number;
  processed_frames?: number;
  total_frames?: number;
  total_person_count?: number;
  processed_video?: string;
  error?: string;
  started_at?: string;
  updated_at?: string;
  completed_at?: string;
  requested_use_cases?: string[];
  executed_use_cases?: string[];
  skipped_use_cases?: string[];
}

interface CameraConnectResponse {
  success?: boolean;
  message?: string;
  camera_id?: string;
  stream_url?: string;
  use_cases?: string[];
}

interface ConnectedCamera {
  camera_id: string;
  camera_name?: string;
  host?: string;
  port?: number;
  status?: string;
  use_cases?: string[];
  connected_at?: string;
  updated_at?: string;
  current_person_count?: number;
  total_person_count?: number;
  total_frames?: number;
  processing_time_seconds?: number;
}

interface AnalyticsData {
  total_videos: number;
  total_persons: number;
  total_processing_time_seconds?: number;
  active_cameras: number;
  todays_detections: number;
  hourly_analytics: { hour: string; detections: number; uploads: number }[];
  person_count_per_video: { video: string; count: number }[];
  recent_uploads: {
    id: string;
    videoName: string;
    uploadDate: string;
    personCount: number;
    status: "completed" | "processing" | "failed";
    processedVideo?: string;
    processingTimeSeconds?: number;
    source?: string;
    useCases?: string[];
    use_cases?: string[];
  }[];
}

interface VideoDetails {
  id: string;
  videoName: string;
  uploadDate: string;
  personCount: number;
  status: "completed" | "processing" | "failed";
  processedVideo: string;
  details: {
    fps?: number;
    total_frames?: number;
    duration_seconds?: number;
    peak_count?: number;
    counts_per_second?: { second: number; count: number }[];
  };
}

async function apiRequest<T>(endpoint: string, options?: RequestInit): Promise<ApiResponse<T>> {
  return requestJson<ApiResponse<T>>(endpoint, options);
}

export async function uploadVideo(file: File, useCases: string[]): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  useCases.forEach((useCase) => formData.append("use_cases", useCase));
  return requestJson<UploadResponse>("/upload-video", {
    method: "POST",
    body: formData,
  });
}

export async function getUploadJobStatus(jobId: string): Promise<UploadJobStatus> {
  const response = await apiRequest<UploadJobStatus>(`/api/jobs/${jobId}`);
  const data = response.data;
  if (data?.processed_video) {
    data.processed_video = toBackendAssetUrl(data.processed_video);
  }
  return data;
}

export async function getAnalytics(): Promise<ApiResponse<AnalyticsData>> {
  return apiRequest<AnalyticsData>("/api/analytics");
}

export async function downloadReport(): Promise<Blob> {
  return requestBlob("/api/analytics/report", { method: "GET" });
}

export async function getVideoDetails(videoId: string): Promise<ApiResponse<VideoDetails>> {
  return apiRequest<VideoDetails>(`/api/videos/${videoId}`);
}

export async function deleteVideo(videoId: string): Promise<void> {
  await requestJson<{ success: boolean; message: string }>(`/api/videos/${videoId}`, {
    method: "DELETE",
  });
}

export async function connectCameraRtsp(
  rtspUrl: string,
  cameraName?: string,
  useCases: string[] = ["person_count"],
): Promise<CameraConnectResponse> {
  return requestJson<CameraConnectResponse>("/api/cameras/connect", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      rtsp_url: rtspUrl,
      camera_name: cameraName?.trim() || undefined,
      use_cases: useCases,
    }),
  });
}

export async function getConnectedCameras(): Promise<ConnectedCamera[]> {
  const response = await apiRequest<ConnectedCamera[]>("/api/cameras");
  return response.data ?? [];
}

export async function getConnectedCamera(cameraId: string): Promise<ConnectedCamera> {
  const response = await apiRequest<ConnectedCamera>(`/api/cameras/${cameraId}`);
  return response.data;
}

export async function deleteConnectedCamera(cameraId: string): Promise<void> {
  await requestJson<{ success: boolean; message: string }>(`/api/cameras/${cameraId}`, {
    method: "DELETE",
  });
}

export { API_BASE_URL };
export type {
  ApiResponse,
  UploadResponse,
  UploadJobStatus,
  AnalyticsData,
  VideoDetails,
  CameraConnectResponse,
  ConnectedCamera,
};
