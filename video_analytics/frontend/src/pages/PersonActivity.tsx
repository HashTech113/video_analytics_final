import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { API_BASE_URL } from "@/lib/api";
import { useEffect, useMemo, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ActivityRecord {
  person_label: string;
  is_known: boolean;
  camera_name: string;
  activity_date: string;
  in_office_ranges: string[]; // e.g. ["09:00:00-12:30:00", "13:00:00-17:45:00"]
}

interface PersonSummary {
  person_identifier: string;
  is_known: boolean;
  session_count: number;
  first_seen: string | null;
  last_seen: string | null;
  cameras: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseRange(range: string): { enter: string; exit: string } {
  const [enter, exit] = range.split("-", 2);
  return { enter: enter ?? "", exit: exit ?? "" };
}

function totalMinutes(ranges: string[]): number {
  return ranges.reduce((acc, r) => {
    const { enter, exit } = parseRange(r);
    if (!enter || !exit || exit === "ongoing") return acc;
    const toMin = (t: string) => {
      const [h, m, s] = t.split(":").map(Number);
      return h * 60 + m + (s ?? 0) / 60;
    };
    return acc + Math.max(0, toMin(exit) - toMin(enter));
  }, 0);
}

function fmtDuration(minutes: number): string {
  if (minutes <= 0) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PersonActivityPage() {
  const today = new Date().toISOString().slice(0, 10);

  const [selectedDate, setSelectedDate] = useState(today);
  const [searchTerm, setSearchTerm] = useState("");
  const [records, setRecords] = useState<ActivityRecord[]>([]);
  const [persons, setPersons] = useState<PersonSummary[]>([]);
  const [dbAvailable, setDbAvailable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"daily" | "persons">("daily");

  // ---- fetch daily records ----
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    const params = new URLSearchParams();
    if (selectedDate) params.set("activity_date", selectedDate);
    if (searchTerm.trim()) params.set("person_identifier", searchTerm.trim());

    fetch(`${API_BASE_URL}/api/activity?${params.toString()}`)
      .then((r) => r.json())
      .then((json) => {
        if (!cancelled) {
          setDbAvailable(json.db_available !== false);
          setRecords(Array.isArray(json.data) ? json.data : []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDbAvailable(false);
          setRecords([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedDate, searchTerm]);

  // ---- fetch persons summary ----
  useEffect(() => {
    fetch(`${API_BASE_URL}/api/activity/persons`)
      .then((r) => r.json())
      .then((json) => {
        setPersons(Array.isArray(json.data) ? json.data : []);
      })
      .catch(() => setPersons([]));
  }, []);

  const knownCount = useMemo(
    () => records.filter((r) => r.is_known).length,
    [records],
  );
  const unknownCount = useMemo(
    () => records.filter((r) => !r.is_known).length,
    [records],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Person Activity</h1>
        <div className="flex items-center gap-2">
          <Button
            variant={activeTab === "daily" ? "default" : "outline"}
            size="sm"
            onClick={() => setActiveTab("daily")}
          >
            Daily Records
          </Button>
          <Button
            variant={activeTab === "persons" ? "default" : "outline"}
            size="sm"
            onClick={() => setActiveTab("persons")}
          >
            All Persons
          </Button>
        </div>
      </div>

      {/* DB unavailable banner */}
      {dbAvailable === false && (
        <Card className="border-destructive/50 bg-destructive/5">
          <CardContent className="pt-4 pb-3 text-sm text-destructive">
            PostgreSQL is not connected. Person-activity data cannot be stored or
            displayed. Set the <code>POSTGRES_HOST</code>,{" "}
            <code>POSTGRES_DB</code>, <code>POSTGRES_USER</code>, and{" "}
            <code>POSTGRES_PASSWORD</code> environment variables and restart the
            backend.
          </CardContent>
        </Card>
      )}

      {activeTab === "daily" && (
        <>
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <Input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="w-[180px]"
            />
            <Input
              type="text"
              placeholder="Search person…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-[220px]"
            />
          </div>

          {/* Stat cards */}
          {dbAvailable && (
            <div className="grid grid-cols-3 gap-4">
              <Card>
                <CardHeader className="pb-1 pt-4 px-5">
                  <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                    Total Persons
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-5 pb-4">
                  <p className="text-3xl font-bold font-mono">{records.length}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-1 pt-4 px-5">
                  <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                    Known Persons
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-5 pb-4">
                  <p className="text-3xl font-bold font-mono text-emerald-600">{knownCount}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-1 pt-4 px-5">
                  <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
                    Unknown Persons
                  </CardTitle>
                </CardHeader>
                <CardContent className="px-5 pb-4">
                  <p className="text-3xl font-bold font-mono text-amber-500">{unknownCount}</p>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Daily records table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Attendance — {selectedDate || "All dates"}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="py-10 text-center text-sm text-muted-foreground">
                  Loading…
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs text-center border-r border-border/40 w-12">
                        Sl.
                      </TableHead>
                      <TableHead className="text-xs border-r border-border/40">
                        Person
                      </TableHead>
                      <TableHead className="text-xs border-r border-border/40">
                        Camera
                      </TableHead>
                      <TableHead className="text-xs text-center border-r border-border/40">
                        Date
                      </TableHead>
                      <TableHead className="text-xs text-center border-r border-border/40">
                        In-Office Time
                      </TableHead>
                      <TableHead className="text-xs text-center border-r border-border/40">
                        Out-of-Office Time
                      </TableHead>
                      <TableHead className="text-xs text-center border-r border-border/40">
                        All Ranges
                      </TableHead>
                      <TableHead className="text-xs text-center">
                        Total Time
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {records.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={8}
                          className="py-8 text-center text-sm text-muted-foreground"
                        >
                          {dbAvailable
                            ? "No activity records for this date."
                            : "Database unavailable."}
                        </TableCell>
                      </TableRow>
                    ) : (
                      records.map((record, idx) => {
                        const sorted = [...(record.in_office_ranges ?? [])].sort();
                        const firstEnter = sorted[0]
                          ? parseRange(sorted[0]).enter
                          : "—";
                        const lastExit = sorted[sorted.length - 1]
                          ? parseRange(sorted[sorted.length - 1]).exit
                          : "—";
                        const mins = totalMinutes(record.in_office_ranges ?? []);

                        return (
                          <TableRow key={`${record.activity_date}-${record.person_label}-${idx}`}>
                            <TableCell className="text-center text-sm font-medium border-r border-border/40">
                              {idx + 1}
                            </TableCell>
                            <TableCell className="border-r border-border/40">
                              <div className="flex items-center gap-2">
                                <span className={`shrink-0 inline-block rounded px-1.5 py-0.5 text-xs font-semibold ${record.is_known ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
                                  {record.is_known ? "Known" : "Unknown"}
                                </span>
                                <span className="text-sm font-medium truncate max-w-[160px]">
                                  {record.person_label}
                                </span>
                              </div>
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground border-r border-border/40">
                              {record.camera_name}
                            </TableCell>
                            <TableCell className="text-sm text-center text-muted-foreground border-r border-border/40">
                              {record.activity_date}
                            </TableCell>
                            <TableCell className="text-sm text-center font-mono border-r border-border/40">
                              {firstEnter}
                            </TableCell>
                            <TableCell className="text-sm text-center font-mono border-r border-border/40">
                              {lastExit === "ongoing" ? (
                                <span className="text-emerald-600 font-semibold">Ongoing</span>
                              ) : (
                                lastExit
                              )}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground border-r border-border/40 max-w-[200px]">
                              <div className="flex flex-wrap gap-1">
                                {sorted.map((r, i) => (
                                  <span
                                    key={i}
                                    className="inline-block bg-muted rounded px-1 py-0.5 font-mono whitespace-nowrap"
                                  >
                                    {r}
                                  </span>
                                ))}
                              </div>
                            </TableCell>
                            <TableCell className="text-sm text-center font-mono font-medium">
                              {fmtDuration(mins)}
                            </TableCell>
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {activeTab === "persons" && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">All Persons</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs w-12 text-center border-r border-border/40">
                    Sl.
                  </TableHead>
                  <TableHead className="text-xs border-r border-border/40">Person</TableHead>
                  <TableHead className="text-xs text-center border-r border-border/40">
                    Sessions
                  </TableHead>
                  <TableHead className="text-xs text-center border-r border-border/40">
                    First Seen
                  </TableHead>
                  <TableHead className="text-xs text-center border-r border-border/40">
                    Last Seen
                  </TableHead>
                  <TableHead className="text-xs">Cameras</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {persons.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="py-8 text-center text-sm text-muted-foreground"
                    >
                      {dbAvailable === false
                        ? "Database unavailable."
                        : "No persons recorded yet."}
                    </TableCell>
                  </TableRow>
                ) : (
                  persons.map((p, idx) => (
                    <TableRow key={p.person_identifier}>
                      <TableCell className="text-center text-sm font-medium border-r border-border/40">
                        {idx + 1}
                      </TableCell>
                      <TableCell className="border-r border-border/40">
                        <div className="flex items-center gap-2">
                          <span className={`shrink-0 inline-block rounded px-1.5 py-0.5 text-xs font-semibold ${p.is_known ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
                            {p.is_known ? "Known" : "Unknown"}
                          </span>
                          <span className="text-sm font-medium">{p.person_identifier}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-sm text-center font-mono border-r border-border/40">
                        {p.session_count}
                      </TableCell>
                      <TableCell className="text-sm text-center text-muted-foreground border-r border-border/40">
                        {p.first_seen ?? "—"}
                      </TableCell>
                      <TableCell className="text-sm text-center text-muted-foreground border-r border-border/40">
                        {p.last_seen ?? "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {p.cameras.join(", ")}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
