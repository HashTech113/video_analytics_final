import { useState } from "react";
import { Camera, Eye, EyeOff, Loader2, Wifi } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { connectCameraRtsp } from "@/lib/api";
import { toast } from "@/hooks/use-toast";

const USE_CASE_OPTIONS = [
  { value: "person_count", label: "Person Count" },
  { value: "person_recognition", label: "Person Recognition" },
];

export default function LiveStream() {
  const [cameraName, setCameraName] = useState("");
  const [cameraIp, setCameraIp] = useState("");
  const [cameraUsername, setCameraUsername] = useState("");
  const [cameraPassword, setCameraPassword] = useState("");
  const [cameraPort, setCameraPort] = useState("554");
  const [selectedUseCases, setSelectedUseCases] = useState<string[]>(["person_count"]);
  const [showPassword, setShowPassword] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionMessage, setConnectionMessage] = useState("");

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

  const handleConnect = async () => {
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

    const numericPort = Number(cameraPort);
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
      const response = await connectCameraRtsp(generatedRtspUrl, cameraName, selectedUseCases);
      setIsConnected(true);
      setConnectionMessage(response.message || "Camera connected successfully.");
      toast({
        title: "Camera connected",
        description: response.message || `RTSP camera stream connected for ${selectedUseCases.join(", ")}.`,
      });
    } catch (error) {
      setIsConnected(false);
      setConnectionMessage("");
      toast({
        title: "Camera connection failed",
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
          Add camera details and connect using an auto-generated RTSP URL.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Camera className="w-4 h-4" />
            Connect Camera
          </CardTitle>
          <CardDescription>
            Enter camera credentials and network details. The RTSP URL is generated automatically.
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
            <Button onClick={handleConnect} disabled={connecting} className="gap-2">
              {connecting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Connecting...
                </>
              ) : (
                <>
                  <Wifi className="w-4 h-4" />
                  Connect Camera
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {isConnected && (
        <Card className="border-primary/40 bg-primary/5">
          <CardHeader>
            <CardTitle className="text-base">Camera Connected</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{connectionMessage}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
