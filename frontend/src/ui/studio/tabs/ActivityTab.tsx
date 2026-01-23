import React, { useEffect, useState } from "react";

type Video = {
  id: string;
};

type AuditEvent = {
  eventId: string;
  type: string;
  actor: string;
  timestamp: number;
  payload: Record<string, any>;
};

export function ActivityTab({ video }: { video: Video | null }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!video?.id) return;

    setLoading(true);
    const params = new URLSearchParams();
    if (filter) params.set("event_type", filter);

    fetch(`/studio/videos/${video.id}/audit?${params.toString()}`)
      .then((r) => r.json())
      .then((j) => setEvents(j.events || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [video?.id, filter]);

  if (!video) return null;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-lg font-semibold">Activity</div>
          <div className="text-sm opacity-70 mt-1">
            Audit log for compliance tracking.
          </div>
        </div>

        <select
          className="border rounded px-2 py-1 text-sm"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">All events</option>
          <option value="create_video">Created</option>
          <option value="policy_check">Policy checks</option>
          <option value="export">Exports</option>
          <option value="update_content_rating">Rating changes</option>
        </select>
      </div>

      <div className="mt-6 border rounded">
        {loading ? (
          <div className="p-4 text-sm opacity-70">Loading...</div>
        ) : events.length === 0 ? (
          <div className="p-4 text-sm opacity-70">No events found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30">
                <th className="text-left p-2 font-medium">Type</th>
                <th className="text-left p-2 font-medium">Actor</th>
                <th className="text-left p-2 font-medium">Time</th>
                <th className="text-left p-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.eventId} className="border-b">
                  <td className="p-2">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        e.type === "policy_check" && !e.payload.allowed
                          ? "bg-red-500/10"
                          : ""
                      }`}
                    >
                      {e.type}
                    </span>
                  </td>
                  <td className="p-2 opacity-70">{e.actor}</td>
                  <td className="p-2 opacity-70">
                    {new Date(e.timestamp * 1000).toLocaleString()}
                  </td>
                  <td className="p-2 text-xs opacity-60 max-w-xs truncate">
                    {e.payload.reason || e.payload.kind || JSON.stringify(e.payload).slice(0, 50)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
