import { Activity, Camera, Clock, Download, Film, Search, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ProcessedVideoPanel } from "@/components/AnalyticsCharts";
import { RecentUploadsTable } from "@/components/RecentUploadsTable";
import { StatCard } from "@/components/StatCard";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  API_BASE_URL,
  deleteConnectedCamera,
  deleteVideo,
  downloadReport,
  getAnalytics,
  getConnectedCamera,
  getConnectedCameras,
  getVideoDetails,
  type AnalyticsData,
  type ConnectedCamera,
  type VideoDetails,
} from "@/lib/api";
import { toBackendAssetUrl } from "@/lib/http";
import { toast } from "@/hooks/use-toast";
import { useEffect, useMemo, useState } from "react";

interface SelectedVideoHourlyEntry {
  second: number;
  detections: number;
  personCount: number;
  uploads: number;
}

type TimelineGranularity = "seconds" | "minutes" | "hours";

interface SelectedVideoTimeline {
  data: SelectedVideoHourlyEntry[];
  ticks: number[];
  endSecond: number;
  granularity: TimelineGranularity;
}

interface SelectedCameraPreview {
  id: string;
  cameraName: string;
  streamUrl: string;
}

interface ActivityRecord {
  activity_date: string;
  person_label: string;
  in_office_ranges: string[];
}

function pickBucketSizeSeconds(durationSeconds: number): { bucketSizeSeconds: number; granularity: TimelineGranularity } {
  if (durationSeconds <= 10 * 60) {
    return { bucketSizeSeconds: 1, granularity: "seconds" };
  }
  if (durationSeconds <= 2 * 60 * 60) {
    return { bucketSizeSeconds: 60, granularity: "minutes" };
  }
  if (durationSeconds <= 12 * 60 * 60) {
    return { bucketSizeSeconds: 30 * 60, granularity: "minutes" };
  }
  if (durationSeconds <= 48 * 60 * 60) {
    return { bucketSizeSeconds: 60 * 60, granularity: "hours" };
  }
  return { bucketSizeSeconds: 2 * 60 * 60, granularity: "hours" };
}

function buildTimelineTicks(endSecond: number, bucketSizeSeconds: number): number[] {
  if (endSecond <= 0) {
    return [0];
  }

  const totalBuckets = Math.max(1, Math.ceil(endSecond / bucketSizeSeconds));
  const targetTickCount = 10;
  const bucketsPerTick = Math.max(1, Math.ceil(totalBuckets / targetTickCount));
  const tickStep = bucketsPerTick * bucketSizeSeconds;

  const ticks: number[] = [];
  for (let t = 0; t <= endSecond; t += tickStep) {
    ticks.push(t);
  }
  if (ticks[ticks.length - 1] !== endSecond) {
    ticks.push(endSecond);
  }
  return ticks;
}

function buildSelectedVideoTimeline(video: VideoDetails): SelectedVideoTimeline {
  const timeline = video.details.counts_per_second ?? [];
  const maxSecondFromData = timeline.length > 0 ? Math.max(...timeline.map((p) => p.second)) : 0;
  const durationSeconds = Math.max(
    maxSecondFromData,
    Math.ceil(video.details.duration_seconds ?? 0),
  );
  const { bucketSizeSeconds, granularity } = pickBucketSizeSeconds(durationSeconds);
  const endSecond = Math.max(durationSeconds, 0);

  const bucketAccumulator = new Map<number, { sum: number; count: number }>();
  const countBySecond = new Map<number, number>();
  for (const point of timeline) {
    countBySecond.set(point.second, point.count);
  }

  let lastKnown = timeline.length > 0 ? timeline[0].count : video.personCount;
  for (let second = 0; second <= endSecond; second += 1) {
    const current = countBySecond.get(second);
    if (current !== undefined) {
      lastKnown = current;
    }
    const bucketStart = Math.floor(second / bucketSizeSeconds) * bucketSizeSeconds;
    const bucket = bucketAccumulator.get(bucketStart) ?? { sum: 0, count: 0 };
    bucket.sum += current ?? lastKnown;
    bucket.count += 1;
    bucketAccumulator.set(bucketStart, bucket);
  }

  const data = Array.from(bucketAccumulator.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([second, bucket]) => ({
      second,
      detections: bucket.count > 0 ? Math.round(bucket.sum / bucket.count) : 0,
      personCount: bucket.count > 0 ? Math.round(bucket.sum / bucket.count) : 0,
      uploads: 1,
    }));

  return {
    data,
    ticks: buildTimelineTicks(endSecond, bucketSizeSeconds),
    endSecond,
    granularity,
  };
}

function formatTimelineTick(value: number, granularity: TimelineGranularity): string {
  if (granularity === "seconds") {
    return `${value}s`;
  }
  if (granularity === "minutes") {
    return `${Math.round(value / 60)}m`;
  }
  return `${Math.round(value / 3600)}h`;
}

function formatTimelineTooltip(value: number, granularity: TimelineGranularity): string {
  if (granularity === "seconds") {
    return `Second ${Math.round(value)}`;
  }
  if (granularity === "minutes") {
    return `Minute ${Math.round(value / 60)}`;
  }
  return `Hour ${Math.round(value / 3600)}`;
}

function formatProcessingTime(seconds?: number): string {
  if (!seconds || seconds <= 0) {
    return "N/A";
  }

  const totalSeconds = Math.round(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainingSeconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m ${remainingSeconds}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  return `${remainingSeconds}s`;
}

export default function Dashboard() {
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [connectedCameras, setConnectedCameras] = useState<ConnectedCamera[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedVideo, setSelectedVideo] = useState<VideoDetails | null>(null);
  const [selectedCameraPreview, setSelectedCameraPreview] = useState<SelectedCameraPreview | null>(null);
  const [selectedLiveCamera, setSelectedLiveCamera] = useState<ConnectedCamera | null>(null);
  const [cameraSearch, setCameraSearch] = useState("");
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedSearchCameraId, setSelectedSearchCameraId] = useState<string | null>(null);
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);
  const [liveCameraSeries, setLiveCameraSeries] = useState<SelectedVideoHourlyEntry[]>([]);
  const [dailyActivityRecords, setDailyActivityRecords] = useState<ActivityRecord[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deletingCameraId, setDeletingCameraId] = useState<string | null>(null);
  const hasViewedVideo = selectedVideo !== null;
  const hasViewedLiveCamera = selectedCameraPreview !== null;
  const today = new Date().toISOString().slice(0, 10);

  const fetchAnalytics = async (showConnectionToast = false) => {
    const statusToast = showConnectionToast
      ? toast({
          title: "Backend connecting",
          description: "Connecting to analytics backend...",
        })
      : null;

    try {
      const [analyticsResponse, camerasResponse] = await Promise.all([
        getAnalytics(),
        getConnectedCameras(),
      ]);

      analyticsResponse.data.recent_uploads = analyticsResponse.data.recent_uploads.map((upload) => ({
        ...upload,
        processedVideo: upload.processedVideo && !upload.processedVideo.startsWith("http")
          ? toBackendAssetUrl(upload.processedVideo)
          : upload.processedVideo,
        useCases: upload.useCases ?? upload.use_cases ?? [],
      }));
      setAnalytics(analyticsResponse.data);
      setConnectedCameras(camerasResponse);
      if (statusToast) {
        statusToast.update({
          id: statusToast.id,
          title: "Backend connected",
          description: "Analytics loaded successfully.",
          variant: "success",
        });
      }
    } catch {
      if (statusToast) {
        statusToast.update({
          id: statusToast.id,
          title: "Analytics unavailable",
          description: "Could not load analytics from backend.",
          variant: "destructive",
        });
      } else {
        toast({
          title: "Analytics unavailable",
          description: "Could not load analytics from backend.",
          variant: "destructive",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics(true);
  }, []);

  useEffect(() => {
    const fetchDailyActivity = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/activity?activity_date=${today}`);
        if (!response.ok) {
          setDailyActivityRecords([]);
          return;
        }
        const json = await response.json();
        setDailyActivityRecords(Array.isArray(json?.data) ? json.data : []);
      } catch {
        setDailyActivityRecords([]);
      }
    };

    void fetchDailyActivity();
  }, [today]);

  const handleDownloadReport = async () => {
    try {
      const blob = await downloadReport();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "analytics_report.csv";
      a.click();
      URL.revokeObjectURL(url);
      toast({ title: "Report downloaded successfully" });
    } catch {
      toast({
        title: "Download failed",
        description: "Could not connect to the backend. Please ensure the server is running.",
        variant: "destructive",
      });
    }
  };

  const handleViewVideo = async (videoId: string) => {
    try {
      const response = await getVideoDetails(videoId);
      const details = response.data;
      if (details.processedVideo && !details.processedVideo.startsWith("http")) {
        details.processedVideo = toBackendAssetUrl(details.processedVideo);
      }
      setSelectedCameraPreview(null);
      setSelectedLiveCamera(null);
      setLiveCameraSeries([]);
      setSelectedVideo(details);
    } catch {
      toast({
        title: "Unable to load video details",
        description: "Could not fetch detailed data for this video.",
        variant: "destructive",
      });
    }
  };

  const handleDeleteVideo = async (videoId: string) => {
    setDeletingId(videoId);
    try {
      await deleteVideo(videoId);
      if (selectedVideo?.id === videoId) {
        setSelectedVideo(null);
      }
      await fetchAnalytics();
      toast({ title: "Video deleted permanently" });
    } catch {
      toast({
        title: "Delete failed",
        description: "Could not delete this video.",
        variant: "destructive",
      });
    } finally {
      setDeletingId(null);
    }
  };

  const handleViewCamera = async (cameraId: string) => {
    try {
      const camera = await getConnectedCamera(cameraId);
      setSelectedVideo(null);
      setSelectedLiveCamera(camera);
      setLiveCameraSeries([]);
      setSelectedCameraPreview({
        id: cameraId,
        cameraName: camera.camera_name || camera.host || cameraId,
        streamUrl: toBackendAssetUrl(`/api/cameras/${cameraId}/stream`),
      });
      toast({
        title: camera.camera_name || "Connected camera",
        description: `${camera.host || "N/A"}:${camera.port || "N/A"} (${camera.status || "connected"})`,
      });
    } catch {
      toast({
        title: "Unable to load camera details",
        description: "Could not fetch details for this camera.",
        variant: "destructive",
      });
    }
  };

  const handleDeleteCamera = async (cameraId: string) => {
    setDeletingCameraId(cameraId);
    try {
      await deleteConnectedCamera(cameraId);
      if (selectedCameraPreview?.id === cameraId) {
        setSelectedCameraPreview(null);
        setSelectedLiveCamera(null);
        setLiveCameraSeries([]);
      }
      await fetchAnalytics();
      toast({ title: "Camera removed successfully" });
    } catch {
      toast({
        title: "Delete failed",
        description: "Could not remove this camera.",
        variant: "destructive",
      });
    } finally {
      setDeletingCameraId(null);
    }
  };

  const selectedVideoTimeline = useMemo(
    () => (selectedVideo ? buildSelectedVideoTimeline(selectedVideo) : null),
    [selectedVideo],
  );

  useEffect(() => {
    if (!selectedCameraPreview?.id) {
      return;
    }

    let cancelled = false;
    setLiveCameraSeries([]);
    const intervalId = window.setInterval(async () => {
      try {
        const camera = await getConnectedCamera(selectedCameraPreview.id);
        if (!cancelled) {
          setSelectedLiveCamera(camera);
          const currentCount = Number(camera.current_person_count ?? 0);
          setLiveCameraSeries((prev) => {
            const nextSecond = prev.length > 0 ? prev[prev.length - 1].second + 1 : 0;
            const nextPoint: SelectedVideoHourlyEntry = {
              second: nextSecond,
              detections: currentCount,
              personCount: currentCount,
              uploads: 1,
            };
            const next = [...prev, nextPoint];
            return next.length > 180 ? next.slice(next.length - 180) : next;
          });
        }
      } catch {
        if (!cancelled) {
          setSelectedLiveCamera(null);
        }
      }
    }, 1000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [selectedCameraPreview?.id]);

  const liveProcessingTime = useMemo(
    () => formatProcessingTime(selectedLiveCamera?.processing_time_seconds),
    [selectedLiveCamera?.processing_time_seconds],
  );

  const zeroedHourlyAnalytics = useMemo(
    () =>
      (analytics?.hourly_analytics ?? []).map((entry) => ({
        ...entry,
        detections: 0,
        uploads: 0,
      })),
    [analytics?.hourly_analytics],
  );

  const hourlyChartData = useMemo(
    () => {
      if (selectedVideoTimeline) {
        return selectedVideoTimeline.data;
      }
      if (selectedLiveCamera && liveCameraSeries.length > 0) {
        return liveCameraSeries;
      }
      return zeroedHourlyAnalytics;
    },
    [selectedVideoTimeline, selectedLiveCamera, liveCameraSeries, zeroedHourlyAnalytics],
  );

  const liveChartEndSecond = useMemo(
    () => (liveCameraSeries.length > 0 ? liveCameraSeries[liveCameraSeries.length - 1].second : 0),
    [liveCameraSeries],
  );
  const liveChartTicks = useMemo(
    () => buildTimelineTicks(liveChartEndSecond, 5),
    [liveChartEndSecond],
  );

  const selectedVideoUseCases = useMemo(() => {
    if (!selectedVideo?.id) return [];
    const match = analytics?.recent_uploads.find((upload) => upload.id === selectedVideo.id);
    return match?.useCases ?? match?.use_cases ?? [];
  }, [analytics?.recent_uploads, selectedVideo?.id]);

  const selectedSummary = useMemo(() => {
    if (selectedLiveCamera) {
      return {
        cameraName: selectedLiveCamera.camera_name || selectedLiveCamera.camera_id || "N/A",
        cameraIp: selectedLiveCamera.host || "N/A",
        date: (selectedLiveCamera.connected_at || selectedLiveCamera.updated_at || "").split("T")[0] || "N/A",
        useCase: selectedLiveCamera.use_cases?.join(", ") || "N/A",
        personCount: selectedLiveCamera.current_person_count ?? 0,
        status: "Live Stream",
      };
    }

    if (selectedVideo) {
      const normalizedStatus = selectedVideo.status === "completed" ? "Processed Completed" : selectedVideo.status;
      return {
        cameraName: selectedVideo.videoName || "N/A",
        cameraIp: "N/A",
        date: (selectedVideo.uploadDate || "").split("T")[0] || "N/A",
        useCase: selectedVideoUseCases.join(", ") || "N/A",
        personCount: selectedVideo.personCount ?? 0,
        status: normalizedStatus,
      };
    }

    return {
      cameraName: "N/A",
      cameraIp: "N/A",
      date: "N/A",
      useCase: "N/A",
      personCount: 0,
      status: "N/A",
    };
  }, [selectedLiveCamera, selectedVideo, selectedVideoUseCases]);

  const cameraSearchResults = useMemo(() => {
    const query = cameraSearch.trim().toLowerCase();
    if (!query) return [];
    return connectedCameras.filter((camera) => {
      const cameraDate = (camera.connected_at || camera.updated_at || "").split("T")[0] || "";
      const matchesDate = !selectedDate || cameraDate === selectedDate;
      const name = (camera.camera_name || "").toLowerCase();
      const ip = (camera.host || "").toLowerCase();
      return matchesDate && (name.includes(query) || ip.includes(query));
    });
  }, [cameraSearch, connectedCameras, selectedDate]);

  useEffect(() => {
    if (!selectedSearchCameraId) {
      return;
    }
    const isStillPresent = cameraSearchResults.some((camera) => camera.camera_id === selectedSearchCameraId);
    if (!isStillPresent) {
      setSelectedSearchCameraId(null);
    }
  }, [cameraSearchResults, selectedSearchCameraId]);

  const handleSearch = async () => {
    const query = cameraSearch.trim();
    if (!query) {
      toast({
        title: "Search term required",
        description: "Enter a camera name or IP address.",
        variant: "destructive",
      });
      return;
    }

    let cameraIdToOpen = selectedSearchCameraId;
    if (!cameraIdToOpen && cameraSearchResults.length === 1) {
      cameraIdToOpen = cameraSearchResults[0].camera_id;
      setSelectedSearchCameraId(cameraIdToOpen);
    }
    if (!cameraIdToOpen) {
      toast({
        title: "Select a camera",
        description: "Choose one camera from search results, then click Search.",
        variant: "destructive",
      });
      return;
    }

    await handleViewCamera(cameraIdToOpen);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        </div>
        <div className="flex items-center gap-2 justify-end">
          <div
            className={`overflow-hidden transition-all duration-300 ease-out ${
              isSearchExpanded ? "max-w-[680px] opacity-100 translate-x-0" : "max-w-0 opacity-0 -translate-x-2 pointer-events-none"
            }`}
          >
            <div className="flex items-center gap-2">
              <Input
                id="analytics-header-search"
                type="text"
                placeholder="Search Camera (Name/IP)"
                value={cameraSearch}
                onChange={(e) => {
                  setCameraSearch(e.target.value);
                  setSelectedSearchCameraId(null);
                }}
                className="w-[240px]"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void handleSearch();
                  }
                }}
              />
              <Input
                id="analytics-header-search-date"
                type="date"
                value={selectedDate}
                onChange={(e) => {
                  setSelectedDate(e.target.value);
                  setSelectedSearchCameraId(null);
                }}
                className="w-[170px]"
              />
              <Button onClick={() => void handleSearch()}>Search</Button>
            </div>
          </div>
          <Button
            type="button"
            variant={isSearchExpanded ? "default" : "outline"}
            size="icon"
            onClick={() => setIsSearchExpanded((prev) => !prev)}
            aria-label="Toggle search options"
            title="Search"
          >
            <Search className="w-4 h-4" />
          </Button>
          <Button onClick={handleDownloadReport} className="gap-2">
            <Download className="w-4 h-4" />
            Download Report
          </Button>
        </div>
      </div>

      {isSearchExpanded && cameraSearch.trim().length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Search Results</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {cameraSearchResults.length > 0 ? (
              cameraSearchResults.map((camera) => {
                const isSelected = selectedSearchCameraId === camera.camera_id;
                return (
                  <button
                    key={camera.camera_id}
                    type="button"
                    className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm ${
                      isSelected ? "border-primary bg-primary/10" : "border-border hover:bg-muted"
                    }`}
                    onClick={() => setSelectedSearchCameraId(camera.camera_id)}
                  >
                    <span className="font-medium">{camera.camera_name || camera.camera_id}</span>
                    <span className="text-muted-foreground">{camera.host || "N/A"}</span>
                  </button>
                );
              })
            ) : (
              <p className="text-sm text-muted-foreground">
                No matching cameras found.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="bg-card rounded-lg border border-border p-5 animate-pulse h-24" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-4">
            <StatCard title="Total Videos" value={analytics?.total_videos ?? 0} icon={Film} />
            <StatCard title="Total Persons" value={analytics?.total_persons ?? 0} icon={Users} />
            <StatCard title="Active Cameras" value={analytics?.active_cameras ?? 0} icon={Camera} />
            <StatCard title="Today's Detections" value={analytics?.todays_detections ?? 0} icon={Activity} />
            <StatCard
              title="Processing Time"
              value={formatProcessingTime(analytics?.total_processing_time_seconds)}
              icon={Clock}
            />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2">
              <ProcessedVideoPanel
                videoUrl={selectedVideo?.processedVideo}
                videoName={selectedVideo?.videoName}
                liveStreamUrl={selectedCameraPreview?.streamUrl}
                liveCameraName={selectedCameraPreview?.cameraName}
                liveCameraId={selectedCameraPreview?.id}
              />
            </div>
            <div className="bg-card rounded-lg border border-border p-5 animate-fade-in space-y-3">
              <h3 className="text-sm font-semibold">
                {selectedLiveCamera ? "Live Camera Summary" : selectedVideo ? "Video Summary" : "Summary"}
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">{selectedLiveCamera ? "Camera" : "Name"}</span>
                  <span className="font-medium text-right truncate max-w-[60%]">{selectedSummary.cameraName}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">IP Address</span>
                  <span className="font-medium">{selectedSummary.cameraIp}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Date</span>
                  <span className="font-medium">{selectedSummary.date}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Use Case</span>
                  <span className="font-medium text-right max-w-[60%] truncate">{selectedSummary.useCase}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Person Count</span>
                  <span className="font-bold font-mono">{selectedSummary.personCount}</span>
                </div>
                {selectedLiveCamera && (
                  <>
                    <div className="flex justify-between gap-2">
                      <span className="text-muted-foreground">Total Persons</span>
                      <span className="font-medium">{selectedLiveCamera.total_person_count ?? 0}</span>
                    </div>
                    <div className="flex justify-between gap-2">
                      <span className="text-muted-foreground">Processing Time</span>
                      <span className="font-medium">{liveProcessingTime}</span>
                    </div>
                  </>
                )}
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Status</span>
                  <span className={`font-medium capitalize ${
                    selectedSummary.status === "Live Stream" || selectedSummary.status === "Processed Completed"
                      ? "text-emerald-600"
                      : "text-muted-foreground"
                  }`}>
                    {selectedSummary.status}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-card rounded-lg border border-border animate-fade-in">
            <div className="p-5 border-b border-border">
              <h3 className="text-sm font-semibold">Processed Videos</h3>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs text-center border-r border-border/40">Sl. No.</TableHead>
                  <TableHead className="text-xs text-center border-r border-border/40">person name</TableHead>
                  <TableHead className="text-xs text-center border-r border-border/40">Date</TableHead>
                  <TableHead className="text-xs text-center border-r border-border/40">In office time</TableHead>
                  <TableHead className="text-xs text-center">Out of office time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dailyActivityRecords.map((record, index) => {
                  const parsedRanges = (record.in_office_ranges ?? [])
                    .map((range) => {
                      const [start, end] = range.split("-", 2);
                      return { start, end };
                    })
                    .filter((range) => range.start && range.end)
                    .sort((a, b) => a.start.localeCompare(b.start));
                  const inOfficeTime = parsedRanges[0]?.start ?? "N/A";
                  const outOfficeTime = parsedRanges[parsedRanges.length - 1]?.end ?? "N/A";

                  return (
                    <TableRow key={`${record.activity_date}-${record.person_label}-${index}`}>
                      <TableCell className="text-sm text-center font-medium border-r border-border/40">{index + 1}</TableCell>
                      <TableCell className="text-sm border-r border-border/40">{record.person_label || "N/A"}</TableCell>
                      <TableCell className="text-sm text-muted-foreground border-r border-border/40">{record.activity_date || "N/A"}</TableCell>
                      <TableCell className="text-sm text-muted-foreground border-r border-border/40">{inOfficeTime}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{outOfficeTime}</TableCell>
                    </TableRow>
                  );
                })}
                {dailyActivityRecords.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-sm text-muted-foreground py-6 text-center">
                      No attendance records yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {connectedCameras.length > 0 && (
            <RecentUploadsTable
              title="Connected Cameras"
              emptyMessage="No connected cameras."
              uploads={connectedCameras.map((camera) => ({
                id: camera.camera_id,
                videoName: camera.camera_name || camera.camera_id,
                uploadDate: (camera.connected_at || camera.updated_at || "").split("T")[0] || "N/A",
                useCases: camera.use_cases ?? [],
                status: (camera.status === "connected" ? "connected" : "disconnected") as "connected" | "disconnected",
              }))}
              onView={handleViewCamera}
              onDelete={handleDeleteCamera}
              deletingId={deletingCameraId}
            />
          )}
        </>
      )}

    </div>
  );
}
