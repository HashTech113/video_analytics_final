import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, useLocation } from "react-router-dom";
import { DashboardLayout } from "@/components/DashboardLayout";
import Dashboard from "./pages/Dashboard";
import UploadVideo from "./pages/UploadVideo";
import LiveStream from "./pages/LiveStream";
import ProcessedVideoPage from "./pages/ProcessedVideo";
import LivePreviewsPage from "./pages/LivePreviews";
import DataPage from "./pages/Data";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

function MountedPage({
  active,
  children,
}: {
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-hidden={!active}
      className={active ? "block" : "hidden"}
    >
      {children}
    </section>
  );
}

function PersistentRouteShell() {
  const { pathname } = useLocation();
  const isUpload = pathname === "/" || pathname === "/upload";
  const isLiveStream = pathname === "/live-stream";
  const isProcessedVideos = pathname === "/processed-video" || pathname === "/processed-video/processed-videos";
  const isLivePreviews = pathname === "/live-previews" || pathname === "/live-preivews";
  const isData = pathname === "/data";
  const isAnalytics = pathname === "/analytics";

  const isKnownPath = (
    isUpload
    || isLiveStream
    || isProcessedVideos
    || isLivePreviews
    || isData
    || isAnalytics
  );

  return (
    <DashboardLayout>
      <MountedPage active={isUpload}>
        <UploadVideo />
      </MountedPage>
      <MountedPage active={isLiveStream}>
        <LiveStream />
      </MountedPage>
      <MountedPage active={isProcessedVideos}>
        <ProcessedVideoPage />
      </MountedPage>
      <MountedPage active={isLivePreviews}>
        <LivePreviewsPage />
      </MountedPage>
      <MountedPage active={isData}>
        <DataPage />
      </MountedPage>
      <MountedPage active={isAnalytics}>
        <Dashboard />
      </MountedPage>
      <MountedPage active={!isKnownPath}>
        <NotFound />
      </MountedPage>
    </DashboardLayout>
  );
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <PersistentRouteShell />
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
