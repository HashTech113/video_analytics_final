import { useEffect, useState } from "react";
import { MoreVertical, Trash2 } from "lucide-react";
import { deleteVideo, getAnalytics, type AnalyticsData } from "@/lib/api";
import { toBackendAssetUrl } from "@/lib/http";
import { toast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default function ProcessedVideoPage() {
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [menuVideoId, setMenuVideoId] = useState<string | null>(null);
  const [deletingVideoId, setDeletingVideoId] = useState<string | null>(null);

  const fetchProcessedVideos = async () => {
    try {
      const analyticsResponse = await getAnalytics();

      analyticsResponse.data.recent_uploads = analyticsResponse.data.recent_uploads.map((upload) => ({
        ...upload,
        processedVideo: upload.processedVideo && !upload.processedVideo.startsWith("http")
          ? toBackendAssetUrl(upload.processedVideo)
          : upload.processedVideo,
        useCases: upload.useCases ?? upload.use_cases ?? [],
      }));
      setAnalytics(analyticsResponse.data);
    } catch {
      toast({
        title: "Unable to load processed videos",
        description: "Could not fetch processed video records.",
        variant: "destructive",
      });
    }
  };

  useEffect(() => {
    fetchProcessedVideos();
  }, []);

  const handleDeleteVideo = async (videoId: string) => {
    setDeletingVideoId(videoId);
    try {
      await deleteVideo(videoId);
      setMenuVideoId(null);
      await fetchProcessedVideos();
      toast({ title: "Video deleted successfully" });
    } catch {
      toast({
        title: "Delete failed",
        description: "Could not delete selected video.",
        variant: "destructive",
      });
    } finally {
      setDeletingVideoId(null);
    }
  };

  const formatUseCaseLabel = (useCase: string) =>
    useCase
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");

  const getStatusClasses = (status: "completed" | "processing" | "failed") => {
    if (status === "completed") {
      return "text-emerald-600";
    }
    if (status === "processing") {
      return "text-amber-600";
    }
    return "text-rose-600";
  };

  const uploadedProcessedVideos = (analytics?.recent_uploads ?? []).filter(
    (upload) => upload.source !== "live_cctv",
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Processed Videos</h1>
      </div>

      {uploadedProcessedVideos.length ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {uploadedProcessedVideos.map((upload) => (
            <Card key={upload.id} className="overflow-hidden">
              <div className="relative aspect-video bg-black border-b border-border">
                {upload.processedVideo ? (
                  <video
                    src={upload.processedVideo}
                    controls
                    preload="metadata"
                    className="h-full w-full object-contain"
                  />
                ) : (
                  <div className="h-full w-full flex items-center justify-center text-xs text-muted-foreground">
                    Preview unavailable
                  </div>
                )}
                <div className="absolute right-2 top-2 z-20">
                  <div className="relative">
                    <Button
                      type="button"
                      variant="secondary"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() =>
                        setMenuVideoId((current) => (current === upload.id ? null : upload.id))
                      }
                      aria-label="More actions"
                      title="More actions"
                    >
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                    {menuVideoId === upload.id && (
                      <div className="absolute right-0 top-9 z-20 min-w-[140px] rounded-md border border-border bg-card p-1 shadow-lg">
                        <button
                          type="button"
                          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-rose-600 hover:bg-secondary disabled:opacity-60"
                          onClick={() => handleDeleteVideo(upload.id)}
                          disabled={deletingVideoId === upload.id}
                        >
                          <Trash2 className="h-4 w-4" />
                          {deletingVideoId === upload.id ? "Deleting..." : "Delete"}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <CardContent className="p-4 space-y-2">
                <p className="text-sm font-medium break-words">{upload.videoName}</p>
                <p className="text-xs text-muted-foreground">Date: {upload.uploadDate || "N/A"}</p>
                <p className="text-xs text-muted-foreground break-words">
                  Features:{" "}
                  {upload.useCases && upload.useCases.length > 0
                    ? upload.useCases.map((useCase) => formatUseCaseLabel(useCase)).join(", ")
                    : "N/A"}
                </p>
                <p className={`text-xs font-medium capitalize ${getStatusClasses(upload.status)}`}>
                  Status: {upload.status}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground text-center">
            No processed videos available yet.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
