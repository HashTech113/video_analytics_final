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
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [streamLoaded, setStreamLoaded] = useState(false);
  const [streamError, setStreamError] = useState(false);

  useEffect(() => {
    const img = imgRef.current;
    if (!isLive || !liveCameraId) {
      setStreamLoaded(false);
      setStreamError(false);
      if (img) img.src = "";
      return;
    }

    setStreamLoaded(false);
    setStreamError(false);
    img!.src = `${API_BASE_URL}/api/cameras/${encodeURIComponent(liveCameraId)}/stream?preview=true`;

    let stopped = false;
    let checkTimer = 0;
    let errorTimeout = 0;

    const checkFrame = () => {
      if (stopped) return;
      if (img && img.naturalWidth > 0) {
        setStreamLoaded(true);
        return;
      }
      checkTimer = window.setTimeout(checkFrame, 150);
    };
    checkTimer = window.setTimeout(checkFrame, 300);

    errorTimeout = window.setTimeout(() => {
      if (!stopped && img && img.naturalWidth === 0) {
        setStreamError(true);
      }
    }, 15000);

    return () => {
      stopped = true;
      window.clearTimeout(checkTimer);
      window.clearTimeout(errorTimeout);
      if (img) img.src = "";
    };
  }, [isLive, liveCameraId]);

  return (
    <div className="bg-card rounded-lg border border-border p-5 animate-fade-in">
      <h3 className="text-sm font-semibold mb-4">{isLive ? "Live Stream" : "Processed Video"}</h3>
      {liveStreamUrl ? (
        <div className="relative rounded-md overflow-hidden bg-black">
          <img
            ref={imgRef}
            alt={liveCameraName || "Live stream"}
            className={`w-full h-[280px] object-contain${streamLoaded ? "" : " hidden"}`}
            onError={() => setStreamError(true)}
          />
          {!streamLoaded && !streamError && (
            <div className="w-full h-[280px] grid place-items-center text-sm text-muted-foreground">
              Connecting live stream...
            </div>
          )}
          {streamError && (
            <div className="absolute inset-0 grid place-items-center px-4 text-center text-sm text-muted-foreground bg-black/70">
              Stream unavailable. Verify backend is running on port 8000 and camera is reachable.
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
