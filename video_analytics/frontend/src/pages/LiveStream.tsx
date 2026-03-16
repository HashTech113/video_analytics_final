import { useEffect, useState } from "react";
import { Camera, Eye, EyeOff, Loader2, Wifi } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  connectCameraRtsp,
  getConnectedCamera,
  updateConnectedCamera,
} from "@/lib/api";
import { toast } from "@/hooks/use-toast";
import { useNavigate, useSearchParams } from "react-router-dom";

const USE_CASE_OPTIONS = [
  { value: "person_count", label: "Person Count" },
  { value: "person_recognition", label: "Person Recognition" },
];

export default function LiveStream() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const editCameraId = searchParams.get("editCameraId")?.trim() || "";
  const isEditing = Boolean(editCameraId);
  const [cameraName, setCameraName] = useState("");
  const [cameraIp, setCameraIp] = useState("");
  const [cameraUsername, setCameraUsername] = useState("");
  const [cameraPassword, setCameraPassword] = useState("");
  const [cameraPort, setCameraPort] = useState("554");
  const [selectedUseCases, setSelectedUseCases] = useState<string[]>([]);
  const [showPassword, setShowPassword] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionMessage, setConnectionMessage] = useState("");
  const [prefilling, setPrefilling] = useState(false);
  const [initialEditSnapshot, setInitialEditSnapshot] = useState<{
    cameraName: string;
    cameraIp: string;
    cameraUsername: string;
    cameraPassword: string;
    cameraPort: string;
    selectedUseCases: string[];
  } | null>(null);

  const normalizeUseCasesForCompare = (useCases: string[]) => {
    const unique = new Set(
      useCases
        .map((value) => (value || "").trim())
        .filter(Boolean),
    );
    return Array.from(unique).sort();
  };

  useEffect(() => {
    if (!isEditing || !editCameraId) {
      return;
    }

    const parseRtspUrl = (rtspUrl: string): {
      ip: string;
      username: string;
      password: string;
      port: string;
    } => {
      try {
        const parsed = new URL(rtspUrl);
        return {
          ip: parsed.hostname || "",
          username: decodeURIComponent(parsed.username || ""),
          password: decodeURIComponent(parsed.password || ""),
          port: parsed.port || "554",
        };
      } catch {
        return {
          ip: "",
          username: "",
          password: "",
          port: "554",
        };
      }
    };

    const loadCameraForEdit = async () => {
      setPrefilling(true);
      try {
        const camera = await getConnectedCamera(editCameraId);
        const parsed = parseRtspUrl(camera.rtsp_url || "");
        const snapshot = {
          cameraName: (camera.camera_name || "").trim(),
          cameraIp: parsed.ip || (camera.host || ""),
          cameraUsername: parsed.username,
          cameraPassword: parsed.password,
          cameraPort: parsed.port || String(camera.port || 554),
          selectedUseCases: normalizeUseCasesForCompare(camera.use_cases ?? []),
        };
        setCameraName(snapshot.cameraName);
        setCameraIp(snapshot.cameraIp);
        setCameraUsername(snapshot.cameraUsername);
        setCameraPassword(snapshot.cameraPassword);
        setCameraPort(snapshot.cameraPort);
        setSelectedUseCases(snapshot.selectedUseCases);
        setInitialEditSnapshot(snapshot);
      } catch {
        toast({
          title: "Unable to load camera",
          description: "Could not load camera details for editing.",
          variant: "destructive",
        });
      } finally {
        setPrefilling(false);
      }
    };

    void loadCameraForEdit();
  }, [editCameraId, isEditing]);

  const toggleUseCase = (useCase: string) => {
    setSelectedUseCases((prev) =>
      prev.includes(useCase)
        ? prev.filter((item) => item !== useCase)
        : [...prev, useCase]
    );
  };

  const generatedRtspUrl = (() => {
    const ip = cameraIp.trim();
    const username = cameraUsername.trim();
    const password = cameraPassword.trim();
    const port = cameraPort.trim();

    if (!ip || !username || !password || !port) {
      return "";
    }

    return `rtsp://${encodeURIComponent(username)}:${encodeURIComponent(password)}@${ip}:${port}/stream1`;
  })();

  const numericPort = Number(cameraPort);
  const isPortValid = Number.isInteger(numericPort) && numericPort >= 1 && numericPort <= 65535;
  const isConnectDisabled =
    connecting
    || prefilling
    || !cameraName.trim()
    || !cameraIp.trim()
    || !cameraUsername.trim()
    || !cameraPassword.trim()
    || !cameraPort.trim()
    || !isPortValid
    || !generatedRtspUrl
    || selectedUseCases.length === 0;

  const handleConnect = async () => {
    if (!cameraName.trim()) {
      toast({
        title: "Camera name required",
        description: "Enter a camera name.",
        variant: "destructive",
      });
      return;
    }

    if (!cameraIp.trim()) {
      toast({
        title: "Camera IP required",
        description: "Enter the camera IP address.",
        variant: "destructive",
      });
      return;
    }

    if (!cameraUsername.trim()) {
      toast({
        title: "Camera username required",
        description: "Enter the camera username.",
        variant: "destructive",
      });
      return;
    }

    if (!cameraPassword.trim()) {
      toast({
        title: "Camera password required",
        description: "Enter the camera password.",
        variant: "destructive",
      });
      return;
    }

    if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) {
      toast({
        title: "Invalid camera port",
        description: "Camera port must be a number between 1 and 65535.",
        variant: "destructive",
      });
      return;
    }

    if (!generatedRtspUrl) {
      toast({
        title: "RTSP URL generation failed",
        description: "Please verify camera details and try again.",
        variant: "destructive",
      });
      return;
    }

    if (selectedUseCases.length === 0) {
      toast({
        title: "Select at least one use case",
        description: "Choose one or more use cases before connecting camera.",
        variant: "destructive",
      });
      return;
    }

    setConnecting(true);
    setIsConnected(false);
    setConnectionMessage("");

    try {
      if (isEditing && initialEditSnapshot) {
        const currentSnapshot = {
          cameraName: cameraName.trim(),
          cameraIp: cameraIp.trim(),
          cameraUsername: cameraUsername.trim(),
          cameraPassword: cameraPassword.trim(),
          cameraPort: cameraPort.trim(),
          selectedUseCases: normalizeUseCasesForCompare(selectedUseCases),
        };
        const hasNoChanges =
          currentSnapshot.cameraName === initialEditSnapshot.cameraName
          && currentSnapshot.cameraIp === initialEditSnapshot.cameraIp
          && currentSnapshot.cameraUsername === initialEditSnapshot.cameraUsername
          && currentSnapshot.cameraPassword === initialEditSnapshot.cameraPassword
          && currentSnapshot.cameraPort === initialEditSnapshot.cameraPort
          && JSON.stringify(currentSnapshot.selectedUseCases) === JSON.stringify(initialEditSnapshot.selectedUseCases);

        if (hasNoChanges) {
          setIsConnected(true);
          setConnectionMessage("Camera updated — No changes made.");
          toast({
            title: "Camera updated",
            description: "Camera updated — No changes made.",
            variant: "success",
          });
          return;
        }
      }

      const response = isEditing
        ? await updateConnectedCamera(editCameraId, generatedRtspUrl, cameraName.trim(), selectedUseCases)
        : await connectCameraRtsp(generatedRtspUrl, cameraName.trim(), selectedUseCases);
      setIsConnected(true);
      setConnectionMessage(
        response.message || (isEditing ? "Camera updated." : "Camera connected successfully."),
      );
      toast({
        title: isEditing ? "Camera updated" : "Camera connected",
        description: response.message || (isEditing ? "Camera updated." : `RTSP camera stream connected for ${selectedUseCases.join(", ")}.`),
        variant: isEditing ? "success" : "default",
      });
    } catch (error) {
      setIsConnected(false);
      setConnectionMessage("");
      toast({
        title: isEditing ? "Camera update failed" : "Camera connection failed",
        description:
          error instanceof Error
            ? error.message
            : "Could not connect the camera stream. Verify URL and backend camera endpoint.",
        variant: "destructive",
      });
    } finally {
      setConnecting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Live Stream</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {isEditing
            ? "Update camera details and save changes."
            : "Add camera details and connect using an auto-generated RTSP URL."}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Camera className="w-4 h-4" />
            {isEditing ? "Edit Camera" : "Connect Camera"}
          </CardTitle>
          <CardDescription>
            {isEditing
              ? "Update camera credentials and network details. The RTSP URL is generated automatically."
              : "Enter camera credentials and network details. The RTSP URL is generated automatically."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="space-y-2">
            <Label htmlFor="cameraName">Camera Name</Label>
            <Input
              id="cameraName"
              placeholder="Front Gate Camera"
              value={cameraName}
              onChange={(e) => setCameraName(e.target.value)}
              disabled={connecting}
            />
            </div>

            <div className="space-y-2">
            <Label htmlFor="cameraIp">Camera IP</Label>
            <Input
              id="cameraIp"
              placeholder="192.168.1.10"
              value={cameraIp}
              onChange={(e) => setCameraIp(e.target.value)}
              disabled={connecting}
            />
            </div>

            <div className="space-y-2">
            <Label htmlFor="cameraUsername">Camera Username</Label>
            <Input
              id="cameraUsername"
              placeholder="admin"
              value={cameraUsername}
              onChange={(e) => setCameraUsername(e.target.value)}
              disabled={connecting}
            />
            </div>

            <div className="space-y-2">
            <Label htmlFor="cameraPassword">Camera Password</Label>
            <div className="relative">
              <Input
                id="cameraPassword"
                type={showPassword ? "text" : "password"}
                placeholder="Enter camera password"
                value={cameraPassword}
                onChange={(e) => setCameraPassword(e.target.value)}
                disabled={connecting}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword((prev) => !prev)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground disabled:opacity-50"
                disabled={connecting}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            </div>

            <div className="space-y-2">
            <Label htmlFor="cameraPort">Camera Port</Label>
            <Input
              id="cameraPort"
              type="number"
              min={1}
              max={65535}
              placeholder="554"
              value={cameraPort}
              onChange={(e) => setCameraPort(e.target.value)}
              disabled={connecting}
            />
            </div>

            <div className="space-y-2">
            <Label htmlFor="generatedRtspUrl">Auto Generated RTSP URL</Label>
            <Input
              id="generatedRtspUrl"
              value={generatedRtspUrl}
              readOnly
              placeholder="rtsp://username:password@camera-ip:port/stream1"
            />
            </div>
          </div>

          <div className="space-y-2">
            <Label>Select Use Case</Label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {USE_CASE_OPTIONS.map((useCase) => {
                const checked = selectedUseCases.includes(useCase.value);
                return (
                  <label
                    key={useCase.value}
                    className="flex items-center gap-2 rounded-md border border-border p-2 text-sm cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleUseCase(useCase.value)}
                      disabled={connecting}
                    />
                    <span>{useCase.label}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button onClick={handleConnect} disabled={isConnectDisabled} className="gap-2">
              {connecting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {isEditing ? "Updating..." : "Connecting..."}
                </>
              ) : (
                <>
                  <Wifi className="w-4 h-4" />
                  {isEditing ? "Update Camera" : "Connect Camera"}
                </>
              )}
            </Button>
            {isEditing && (
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate("/live-stream")}
                disabled={connecting}
              >
                Cancel Edit
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {isConnected && (
        <Card className="border-primary/40 bg-primary/5">
          <CardHeader>
            <CardTitle className="text-base">Camera Connected</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">{connectionMessage}</p>
            <Button onClick={() => navigate("/live-previews")}>
              Go to Live Previews
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
