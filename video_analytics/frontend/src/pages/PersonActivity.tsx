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

/** "HH:MM:SS" → "HH:MM" */
function fmtHHMM(t: string): string {
  if (!t || t === "ongoing") return t;
  const parts = t.split(":");
  return `${parts[0] ?? "00"}:${parts[1] ?? "00"}`;
}

/** "YYYY-MM-DD" → "DD-MM-YYYY" */
function fmtDate(d: string): string {
  const [y, m, day] = d.split("-");
  return `${day}-${m}-${y}`;
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
                      <TableHead className="text-xs text-center">
                        Out-of-Office Time
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {records.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={6}
                          className="py-8 text-center text-sm text-muted-foreground"
                        >
                          {dbAvailable
                            ? "No activity records for this date."
                            : "Database unavailable."}
                        </TableCell>
                      </TableRow>
                    ) : (
                      records.flatMap((record, idx) => {
                        const sorted = [...(record.in_office_ranges ?? [])].sort();
                        const rowCount = Math.max(1, sorted.length);

                        if (sorted.length === 0) {
                          return [
                            <TableRow key={`${idx}-empty`}>
                              <TableCell className="text-center text-sm font-medium border-r border-border/40 align-top">
                                {idx + 1}
                              </TableCell>
                              <TableCell className="border-r border-border/40 align-top">
                                <div className="flex flex-col gap-1">
                                  <span className={`self-start inline-block rounded px-1.5 py-0.5 text-xs font-semibold ${record.is_known ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
                                    {record.is_known ? "Known" : "Unknown"}
                                  </span>
                                  <span className="text-sm font-medium">{record.person_label}</span>
                                </div>
                              </TableCell>
                              <TableCell className="text-sm text-muted-foreground border-r border-border/40 align-top">
                                {record.camera_name}
                              </TableCell>
                              <TableCell className="text-sm text-center text-muted-foreground border-r border-border/40 align-top">
                                {fmtDate(record.activity_date)}
                              </TableCell>
                              <TableCell className="text-sm text-center font-mono border-r border-border/40">—</TableCell>
                              <TableCell className="text-sm text-center font-mono">—</TableCell>
                            </TableRow>,
                          ];
                        }

                        return sorted.map((range, rangeIdx) => {
                          const { enter, exit } = parseRange(range);
                          const nextRange = sorted[rangeIdx + 1];
                          const nextEnter = nextRange ? parseRange(nextRange).enter : null;

                          const inOffice =
                            exit === "ongoing"
                              ? `${fmtHHMM(enter)} - Ongoing`
                              : `${fmtHHMM(enter)} - ${fmtHHMM(exit)}`;

                          const outOfOffice =
                            nextEnter
                              ? `${fmtHHMM(exit)} - ${fmtHHMM(nextEnter)}`
                              : "—";

                          return (
                            <TableRow key={`${idx}-${rangeIdx}`}>
                              {rangeIdx === 0 && (
                                <>
                                  <TableCell
                                    rowSpan={rowCount}
                                    className="text-center text-sm font-medium border-r border-border/40 align-top"
                                  >
                                    {idx + 1}
                                  </TableCell>
                                  <TableCell
                                    rowSpan={rowCount}
                                    className="border-r border-border/40 align-top"
                                  >
                                    <div className="flex flex-col gap-1">
                                      <span className={`self-start inline-block rounded px-1.5 py-0.5 text-xs font-semibold ${record.is_known ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
                                        {record.is_known ? "Known" : "Unknown"}
                                      </span>
                                      <span className="text-sm font-medium">{record.person_label}</span>
                                    </div>
                                  </TableCell>
                                  <TableCell
                                    rowSpan={rowCount}
                                    className="text-sm text-muted-foreground border-r border-border/40 align-top"
                                  >
                                    {record.camera_name}
                                  </TableCell>
                                  <TableCell
                                    rowSpan={rowCount}
                                    className="text-sm text-center text-muted-foreground border-r border-border/40 align-top"
                                  >
                                    {fmtDate(record.activity_date)}
                                  </TableCell>
                                </>
                              )}
                              <TableCell className="text-sm text-center font-mono border-r border-border/40">
                                {inOffice}
                              </TableCell>
                              <TableCell className="text-sm text-center font-mono text-muted-foreground">
                                {outOfOffice}
                              </TableCell>
                            </TableRow>
                          );
                        });
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
