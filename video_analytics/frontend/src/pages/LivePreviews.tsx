import { useEffect, useRef, useState } from "react";
import { Maximize2, MonitorPlay, MoreVertical, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { deleteConnectedCamera, getConnectedCameras, type ConnectedCamera } from "@/lib/api";
import { toBackendAssetUrl } from "@/lib/http";
import { toast } from "@/hooks/use-toast";

export default function LivePreviewsPage() {
  const [cameras, setCameras] = useState<ConnectedCamera[]>([]);
  const [loading, setLoading] = useState(true);
  const [menuCameraId, setMenuCameraId] = useState<string | null>(null);
  const [deletingCameraId, setDeletingCameraId] = useState<string | null>(null);
  const previewRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const pendingRemovalIdsRef = useRef<Set<string>>(new Set());

  const fetchCameras = async (showError = false) => {
    try {
      const data = await getConnectedCameras();
      setCameras(
        data.filter((camera) => !pendingRemovalIdsRef.current.has(camera.camera_id)),
      );
    } catch {
      if (showError) {
        toast({
          title: "Unable to load live previews",
          description: "Could not fetch connected camera streams.",
          variant: "destructive",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCameras(true);
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
      pendingRemovalIdsRef.current.delete(cameraId);
      toast({ title: "Camera removed successfully" });
    } catch {
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
            No live cameras connected yet.
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
                      <div className="absolute right-0 top-9 z-20 min-w-[160px] rounded-md border border-border bg-card p-1 shadow-lg">
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
