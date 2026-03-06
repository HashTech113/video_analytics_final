import { useEffect, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { API_BASE_URL } from "@/config/env";

interface HourlyAnalyticsEntry {
  hour?: string;
  personCount?: number;
  detections: number;
  uploads: number;
}

interface HourlyAnalyticsChartProps {
  data: HourlyAnalyticsEntry[];
  title?: string;
  xAxisLabel?: string;
  xDataKey?: "hour" | "second";
  xAxisType?: "category" | "number";
  xTicks?: number[];
  xAxisInterval?: number | "preserveStart" | "preserveEnd" | "preserveStartEnd";
  xDomain?: [number | "dataMin" | "dataMax", number | "dataMin" | "dataMax"];
  xTickFormatter?: (value: number | string) => string;
  tooltipLabelFormatter?: (value: number | string) => string;
  yDataKey?: "detections" | "personCount";
  yAxisLabel?: string;
  lineName?: string;
}

interface ProcessedVideoPanelProps {
  videoUrl?: string;
  videoName?: string;
  liveStreamUrl?: string;
  liveCameraName?: string;
  liveCameraId?: string;
}

export function HourlyAnalyticsChart({
  data,
  title = "Hourly Analytics",
  xAxisLabel = "Duration",
  xDataKey = "hour",
  xAxisType = "category",
  xTicks,
  xAxisInterval = "preserveEnd",
  xDomain,
  xTickFormatter,
  tooltipLabelFormatter,
  yDataKey = "detections",
  yAxisLabel = "Counts",
  lineName = "Count",
}: HourlyAnalyticsChartProps) {
  return (
    <div className="bg-card rounded-lg border border-border p-5 animate-fade-in">
      <h3 className="text-sm font-semibold mb-4">{title}</h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis
            dataKey={xDataKey}
            type={xAxisType}
            ticks={xTicks}
            interval={xAxisInterval}
            tickFormatter={xTickFormatter}
            allowDecimals={false}
            domain={xAxisType === "number" ? (xDomain ?? ["dataMin", "dataMax"]) : undefined}
            tick={{ fontSize: 12 }}
            stroke="hsl(var(--muted-foreground))"
            label={{ value: xAxisLabel, position: "insideBottom", offset: -5 }}
          />
          <YAxis
            tick={{ fontSize: 12 }}
            stroke="hsl(var(--muted-foreground))"
            allowDecimals={false}
            label={{ value: yAxisLabel, angle: -90, position: "insideLeft" }}
          />
          <Tooltip
            labelFormatter={tooltipLabelFormatter}
            contentStyle={{
              backgroundColor: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              borderRadius: "8px",
              fontSize: "12px",
            }}
          />
          <Line
            type="monotone"
            dataKey={yDataKey}
            stroke="hsl(var(--chart-1))"
            strokeWidth={2}
            dot={{ r: 4, fill: "hsl(var(--chart-1))" }}
            activeDot={{ r: 6, fill: "hsl(var(--chart-1))" }}
            name={lineName}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ProcessedVideoPanel({
  videoUrl,
  videoName,
  liveStreamUrl,
  liveCameraName,
  liveCameraId,
}: ProcessedVideoPanelProps) {
  const isLive = Boolean(liveStreamUrl);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [webrtcReady, setWebrtcReady] = useState(false);
  const [webrtcFailed, setWebrtcFailed] = useState(false);

  useEffect(() => {
    if (!isLive || !liveCameraId) {
      setWebrtcReady(false);
      setWebrtcFailed(false);
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
      return;
    }

    let disposed = false;
    const pc = new RTCPeerConnection();
    setWebrtcReady(false);
    setWebrtcFailed(false);

    const setup = async () => {
      try {
        pc.addTransceiver("video", { direction: "recvonly" });
        pc.ontrack = (event) => {
          if (disposed || !videoRef.current) return;
          const [stream] = event.streams;
          videoRef.current.srcObject = stream;
          setWebrtcReady(true);
        };

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const response = await fetch(`${API_BASE_URL}/api/cameras/${liveCameraId}/webrtc-offer`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            sdp: offer.sdp,
            type: offer.type,
          }),
        });

        if (!response.ok) {
          throw new Error("WebRTC signaling failed.");
        }

        const payload = await response.json();
        const answer = payload?.data;
        if (!answer?.sdp || !answer?.type) {
          throw new Error("Invalid WebRTC answer payload.");
        }

        await pc.setRemoteDescription(answer);
      } catch {
        if (!disposed) {
          setWebrtcReady(false);
          setWebrtcFailed(true);
        }
      }
    };

    setup();

    return () => {
      disposed = true;
      const stream = videoRef.current?.srcObject as MediaStream | null;
      stream?.getTracks().forEach((track) => track.stop());
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
      pc.close();
    };
  }, [isLive, liveCameraId]);

  return (
    <div className="bg-card rounded-lg border border-border p-5 animate-fade-in">
      <h3 className="text-sm font-semibold mb-4">{isLive ? "Live Stream" : "Processed Video"}</h3>
      {liveStreamUrl ? (
        <div className="rounded-md overflow-hidden bg-black">
          {webrtcReady ? (
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="w-full h-[280px] object-contain"
            />
          ) : webrtcFailed ? (
            <img src={liveStreamUrl} alt={liveCameraName || "Live stream"} className="w-full h-[280px] object-contain" />
          ) : (
            <div className="w-full h-[280px] grid place-items-center text-sm text-muted-foreground">
              Connecting live stream...
            </div>
          )}
        </div>
      ) : videoUrl ? (
        <div className="rounded-md overflow-hidden bg-black">
          <video src={videoUrl} controls className="w-full h-[280px] object-contain" />
        </div>
      ) : (
        <div className="h-[280px] rounded-md border border-dashed border-border grid place-items-center text-sm text-muted-foreground px-4 text-center">
          Click View on a processed or live-stream record to preview here.
        </div>
      )}
      {(isLive ? liveCameraName : videoName) && (
        <p className="text-xs text-muted-foreground mt-3 truncate">{isLive ? liveCameraName : videoName}</p>
      )}
    </div>
  );
}
