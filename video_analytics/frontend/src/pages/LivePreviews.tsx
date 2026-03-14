import { useEffect, useRef, useState } from "react";
import { Maximize2, MonitorPlay, MoreVertical, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { deleteConnectedCamera, getConnectedCameras, type ConnectedCamera } from "@/lib/api";
import { toBackendAssetUrl } from "@/lib/http";
import { toast } from "@/hooks/use-toast";
import { useNavigate } from "react-router-dom";

export default function LivePreviewsPage() {
  const navigate = useNavigate();
  const [cameras, setCameras] = useState<ConnectedCamera[]>([]);
  const [loading, setLoading] = useState(true);
  const [menuCameraId, setMenuCameraId] = useState<string | null>(null);
  const [deletingCameraId, setDeletingCameraId] = useState<string | null>(null);
  const previewRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const pendingRemovalIdsRef = useRef<Set<string>>(new Set());
  const removedCameraIdsRef = useRef<Set<string>>(new Set());
  const backendConnectedRef = useRef(false);

  const fetchCameras = async (showStatus = false) => {
    try {
      const data = await getConnectedCameras();
      setCameras(
        data.filter(
          (camera) =>
            !pendingRemovalIdsRef.current.has(camera.camera_id)
            && !removedCameraIdsRef.current.has(camera.camera_id),
        ),
      );
      if (showStatus || !backendConnectedRef.current) {
        toast({
          title: "Backend connected successfully",
          variant: "success",
        });
      }
      backendConnectedRef.current = true;
    } catch {
      backendConnectedRef.current = false;
      if (showStatus) {
        toast({
          title: "Unable to connect backend",
          variant: "destructive",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleEditCamera = (cameraId: string) => {
    setMenuCameraId(null);
    navigate(`/live-stream?editCameraId=${encodeURIComponent(cameraId)}`);
  };

  useEffect(() => {
    void fetchCameras(true);
    const intervalId = window.setInterval(() => {
      void fetchCameras(false);
    }, 2500);
    return () => {
      window.clearInterval(intervalId);
    };
  }, []);

  const handleFullscreen = async (cameraId: string) => {
    const target = previewRefs.current[cameraId];
    if (!target) {
      return;
    }
    try {
      await target.requestFullscreen();
    } catch {
      toast({
        title: "Fullscreen unavailable",
        description: "Could not open this camera preview in fullscreen.",
        variant: "destructive",
      });
    }
  };

  const handleRemoveCamera = async (cameraId: string) => {
    const previousCameras = cameras;
    pendingRemovalIdsRef.current.add(cameraId);
    setCameras((prev) => prev.filter((camera) => camera.camera_id !== cameraId));
    setMenuCameraId(null);
    setDeletingCameraId(cameraId);
    try {
      await deleteConnectedCamera(cameraId);
      removedCameraIdsRef.current.add(cameraId);
      pendingRemovalIdsRef.current.delete(cameraId);
      await fetchCameras(false);
      toast({ title: "Camera removed successfully" });
    } catch {
      removedCameraIdsRef.current.delete(cameraId);
      pendingRemovalIdsRef.current.delete(cameraId);
      setCameras(previousCameras);
      toast({
        title: "Failed to remove camera",
        description: "Could not remove selected camera.",
        variant: "destructive",
      });
    } finally {
      setDeletingCameraId(null);
    }
  };

  const formatUseCaseLabel = (useCase: string) =>
    useCase
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Live Previews</h1>
        <p className="text-sm text-muted-foreground mt-1">
          All cameras added through Live Stream are shown here.
        </p>
      </div>

      {loading ? (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground">
            Loading live previews...
          </CardContent>
        </Card>
      ) : cameras.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground">
            Setup complete. Start connecting cameras for further processing.
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {cameras.map((camera) => (
            <Card key={camera.camera_id}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <MonitorPlay className="w-4 h-4" />
                    {camera.camera_name || camera.host || camera.camera_id}
                  </CardTitle>
                  <div className="relative flex items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleFullscreen(camera.camera_id)}
                      aria-label="View in fullscreen"
                      title="View fullscreen"
                    >
                      <Maximize2 className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() =>
                        setMenuCameraId((current) =>
                          current === camera.camera_id ? null : camera.camera_id,
                        )
                      }
                      aria-label="More actions"
                      title="More actions"
                    >
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                    {menuCameraId === camera.camera_id && (
                      <div className="absolute right-0 top-9 z-20 min-w-[180px] rounded-md border border-border bg-card p-1 shadow-lg">
                        <button
                          type="button"
                          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-secondary disabled:opacity-60"
                          onClick={() => handleEditCamera(camera.camera_id)}
                          disabled={deletingCameraId === camera.camera_id}
                        >
                          <Pencil className="h-4 w-4" />
                          Edit camera
                        </button>
                        <button
                          type="button"
                          className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-rose-600 hover:bg-secondary disabled:opacity-60"
                          onClick={() => handleRemoveCamera(camera.camera_id)}
                          disabled={deletingCameraId === camera.camera_id}
                        >
                          <Trash2 className="h-4 w-4" />
                          {deletingCameraId === camera.camera_id ? "Removing..." : "Remove camera"}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  {camera.host || "N/A"}:{camera.port || "N/A"} ({camera.status || "connected"})
                </p>
                <p className="text-xs text-muted-foreground">
                  Use Case:{" "}
                  {camera.use_cases && camera.use_cases.length > 0
                    ? camera.use_cases.map((useCase) => formatUseCaseLabel(useCase)).join(", ")
                    : "N/A"}
                </p>
              </CardHeader>
              <CardContent>
                <div
                  ref={(el) => {
                    previewRefs.current[camera.camera_id] = el;
                  }}
                  className="live-preview-container rounded-md overflow-hidden bg-black border border-border"
                >
                  <img
                    src={toBackendAssetUrl(`/api/cameras/${camera.camera_id}/stream`)}
                    alt={camera.camera_name || "Live preview"}
                    className="live-preview-image w-full h-[220px] object-contain"
                  />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
