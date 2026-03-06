import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, X, FileVideo, Loader2, CheckCircle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { getUploadJobStatus, uploadVideo } from "@/lib/api";
import { toast } from "@/hooks/use-toast";

const SUPPORTED_VIDEO_EXTENSIONS = [
  "mp4",
  "avi",
  "mov",
  "mkv",
  "webm",
  "flv",
  "wmv",
  "m4v",
  "mpg",
  "mpeg",
  "3gp",
  "ts",
  "m2ts",
];

function isSupportedVideoFile(file: File) {
  const extension = file.name.includes(".")
    ? file.name.split(".").pop()?.toLowerCase() ?? ""
    : "";
  return file.type.startsWith("video/") || SUPPORTED_VIDEO_EXTENSIONS.includes(extension);
}

const USE_CASE_OPTIONS = [
  { value: "person_count", label: "Person Count" },
  { value: "person_recognition", label: "Person Recognition" },
];

export default function UploadVideo() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [processedVideoUrl, setProcessedVideoUrl] = useState<string | null>(null);
  const [processingProgress, setProcessingProgress] = useState(0);
  const [processingSeconds, setProcessingSeconds] = useState(0);
  const [selectedUseCases, setSelectedUseCases] = useState<string[]>(["person_count"]);
  const processingStartTimeRef = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const toggleUseCase = (useCase: string) => {
    setSelectedUseCases((prev) =>
      prev.includes(useCase)
        ? prev.filter((item) => item !== useCase)
        : [...prev, useCase]
    );
  };

  useEffect(() => {
    if (!uploading) {
      return;
    }

    const elapsedTimer = window.setInterval(() => {
      setProcessingSeconds((prev) => prev + 1);
    }, 1000);

    return () => {
      window.clearInterval(elapsedTimer);
    };
  }, [uploading]);

  const handleFileSelect = useCallback((selectedFile: File) => {
    if (!isSupportedVideoFile(selectedFile)) {
      toast({
        title: "Invalid file",
        description: "Please select a common video format (MP4, AVI, MOV, MKV, WEBM, FLV, WMV, MPEG, etc.).",
        variant: "destructive",
      });
      return;
    }
    setFile(selectedFile);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile) handleFileSelect(droppedFile);
    },
    [handleFileSelect]
  );

  const handleSubmit = async () => {
    if (!file) return;
    if (selectedUseCases.length === 0) {
      toast({
        title: "Select at least one use case",
        description: "Choose one or more use cases before submitting.",
        variant: "destructive",
      });
      return;
    }

    setProcessedVideoUrl(null);
    setProcessingProgress(0);
    setProcessingSeconds(0);
    processingStartTimeRef.current = Date.now();
    setUploading(true);
    try {
      const response = await uploadVideo(file, selectedUseCases);
      toast({
        title: "Upload accepted",
        description: `Processing started for ${selectedUseCases.join(", ")}.`,
      });

      while (true) {
        const status = await getUploadJobStatus(response.job_id);
        setProcessingProgress(status.progress ?? 0);

        if (status.status === "completed") {
          setProcessedVideoUrl(status.processed_video ?? null);
          setProcessingProgress(100);
          toast({
            title: "Processing complete",
            description: `Total person count: ${status.total_person_count ?? 0}`,
          });
          break;
        }

        if (status.status === "failed") {
          throw new Error(status.error || "Video processing failed.");
        }

        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }

      if (processingStartTimeRef.current) {
        const elapsedSeconds = Math.max(
          1,
          Math.round((Date.now() - processingStartTimeRef.current) / 1000)
        );
        setProcessingSeconds(elapsedSeconds);
      }
    } catch (error) {
      toast({
        title: "Processing failed",
        description: error instanceof Error
          ? error.message
          : "Could not connect to the backend. Please ensure the Python server is running.",
        variant: "destructive",
      });
    } finally {
      setUploading(false);
    }
  };

  const clearFile = () => {
    setFile(null);
    setProcessedVideoUrl(null);
    setProcessingProgress(0);
    setProcessingSeconds(0);
    processingStartTimeRef.current = null;
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Upload Video</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Upload a video file for analysis. Supported formats include MP4, AVI, MOV, MKV, WEBM, FLV, WMV, and MPEG.
        </p>
      </div>

      {!file ? (
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className="border-2 border-dashed border-border rounded-lg p-12 text-center cursor-pointer transition-colors hover:border-primary hover:bg-primary/5"
        >
          <Upload className="w-10 h-10 mx-auto text-muted-foreground mb-4" />
          <p className="text-sm font-medium">Drag & drop your video here</p>
          <p className="text-xs text-muted-foreground mt-1">or click to browse files</p>
          <input
            ref={inputRef}
            type="file"
            accept="video/*,.mp4,.avi,.mov,.mkv,.webm,.flv,.wmv,.m4v,.mpg,.mpeg,.3gp,.ts,.m2ts"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) handleFileSelect(f);
            }}
          />
        </div>
      ) : (
        <div className="space-y-4 animate-fade-in">
          {/* File info */}
          <div className="flex items-center justify-between bg-card rounded-lg border border-border p-4">
            <div className="flex items-center gap-3">
              <FileVideo className="w-5 h-5 text-primary" />
              <div>
                <p className="text-sm font-medium">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(file.size / (1024 * 1024)).toFixed(2)} MB
                </p>
              </div>
            </div>
            <Button variant="ghost" size="icon" onClick={clearFile}>
              <X className="w-4 h-4" />
            </Button>
          </div>

          {/* Submit / Processed Result */}
          {processedVideoUrl ? (
            <>
              <Card className="border-primary/30 bg-primary/5">
                <CardHeader className="flex flex-row items-center gap-2 pb-3">
                  <CheckCircle className="w-5 h-5 text-primary" />
                  <CardTitle className="text-base">Processed Video</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-sm text-muted-foreground">
                    Video analysis is complete and the output has been generated successfully.
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Use cases: {selectedUseCases.join(", ")}
                  </p>
                  <p className="text-sm font-medium">Processing time: {processingSeconds}s</p>
                  <Button onClick={clearFile} className="gap-2">
                    <RotateCcw className="w-4 h-4" />
                    Upload Another
                  </Button>
                </CardContent>
              </Card>

              <Card className="border-border">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Processed Video Preview</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="rounded-lg border border-border overflow-hidden bg-black">
                    <video
                      src={processedVideoUrl}
                      controls
                      className="w-full max-h-[420px]"
                    />
                  </div>
                </CardContent>
              </Card>
            </>
          ) : (
            <div className="space-y-3">
              <Card className="border-border">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Select Use Case</CardTitle>
                </CardHeader>
                <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
                          disabled={uploading}
                        />
                        <Label className="cursor-pointer">{useCase.label}</Label>
                      </label>
                    );
                  })}
                </CardContent>
              </Card>

              <div className="flex gap-3">
                <Button onClick={handleSubmit} disabled={uploading} className="gap-2">
                  {uploading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4" />
                      Submit for Analysis
                    </>
                  )}
                </Button>
                <Button variant="outline" onClick={clearFile} disabled={uploading}>
                  Cancel
                </Button>
              </div>
              {uploading && (
                <div className="space-y-2 rounded-md border border-border p-3">
                  <div className="flex items-center justify-between text-sm">
                    <span>Processing time: {processingSeconds}s</span>
                    <span>{processingProgress}%</span>
                  </div>
                  <Progress value={processingProgress} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
