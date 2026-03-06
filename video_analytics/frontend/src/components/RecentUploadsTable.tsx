import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

interface UploadEntry {
  id: string;
  videoName: string;
  uploadDate: string;
  useCases?: string[];
  status: "completed" | "processing" | "failed" | "connected" | "disconnected";
}

interface RecentUploadsTableProps {
  title?: string;
  emptyMessage?: string;
  uploads: UploadEntry[];
  onView?: (videoId: string) => void;
  onDelete?: (videoId: string) => void;
  showActions?: boolean;
  deletingId?: string | null;
}

export function RecentUploadsTable({
  title = "Processed Videos",
  emptyMessage = "No uploads available yet.",
  uploads,
  onView,
  onDelete,
  showActions = true,
  deletingId,
}: RecentUploadsTableProps) {
  const formatUseCaseLabel = (useCase: string) =>
    useCase
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");

  const getStatusClasses = (status: UploadEntry["status"]) => {
    if (status === "connected" || status === "completed") {
      return "text-emerald-600";
    }
    if (status === "processing") {
      return "text-amber-600";
    }
    return "text-rose-600";
  };

  return (
    <div className="bg-card rounded-lg border border-border animate-fade-in">
      <div className="p-5 border-b border-border">
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs text-center border-r border-border/40">Sl. No.</TableHead>
            <TableHead className="text-xs text-center border-r border-border/40">Video Name</TableHead>
            <TableHead className="text-xs text-center border-r border-border/40">Upload Date</TableHead>
            <TableHead className="text-xs text-center border-r border-border/40">Features</TableHead>
            <TableHead className="text-xs text-center">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {uploads.map((upload, index) => (
            <TableRow key={upload.id}>
              <TableCell className="text-sm text-center font-medium border-r border-border/40">{index + 1}</TableCell>
              <TableCell className="font-mono text-sm max-w-[180px] whitespace-normal break-words border-r border-border/40" title={upload.videoName}>
                {upload.videoName}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground border-r border-border/40">{upload.uploadDate}</TableCell>
              <TableCell className="text-sm text-muted-foreground border-r border-border/40 max-w-[220px] whitespace-normal break-words">
                {upload.useCases && upload.useCases.length > 0
                  ? upload.useCases.map((useCase) => formatUseCaseLabel(useCase)).join(", ")
                  : "N/A"}
              </TableCell>
              <TableCell className="text-sm">
                <div className="flex items-center gap-2">
                  <span className={`capitalize font-medium ${getStatusClasses(upload.status)}`}>
                    {upload.status}
                  </span>
                  {showActions && onView && onDelete && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => onView(upload.id)}>
                        View
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={deletingId === upload.id}
                        onClick={() => onDelete(upload.id)}
                      >
                        {deletingId === upload.id ? "Deleting..." : "Delete"}
                      </Button>
                    </>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
          {uploads.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-sm text-muted-foreground py-6 text-center">
                {emptyMessage}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
