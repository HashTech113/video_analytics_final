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
import PersonActivityPage from "./pages/PersonActivity";
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
  const normalizedPath = pathname.endsWith("/") && pathname !== "/" ? pathname.slice(0, -1) : pathname;
  const isUpload = normalizedPath === "/" || normalizedPath === "/upload";
  const isLiveStream = normalizedPath === "/live-stream";
  const isProcessedVideos = normalizedPath === "/processed-video" || normalizedPath === "/processed-video/processed-videos";
  const isLivePreviews = normalizedPath === "/live-previews" || normalizedPath === "/live-preivews";
  const isData = normalizedPath === "/data";
  const isAnalytics = normalizedPath === "/analytics";
  const isPersonActivity = normalizedPath === "/person-activity";
  const isKnownPath = (
    isUpload
    || isLiveStream
    || isProcessedVideos
    || isLivePreviews
    || isData
    || isAnalytics
    || isPersonActivity
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
      <MountedPage active={isPersonActivity}>
        <PersonActivityPage />
      </MountedPage>
      {!isKnownPath ? <NotFound /> : null}
    </DashboardLayout>
  );
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter
        future={{
          v7_startTransition: true,
          v7_relativeSplatPath: true,
        }}
      >
        <PersistentRouteShell />
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
