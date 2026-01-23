import React from "react";

export type LibraryFilter = {
  q: string;
  status?: string;
  preset?: string;
  contentRating?: string;
};

type Props = {
  filter: LibraryFilter;
  onChange: (f: LibraryFilter) => void;
  collapsed?: boolean;
  children?: React.ReactNode;
};

/**
 * Left sidebar library rail with filters.
 *
 * Filters:
 * - Search (title, tags, owner)
 * - Status (draft, in_review, approved, archived)
 * - Platform preset
 * - Content rating (SFW only / Mature allowed)
 */
export function StudioLibraryRail(props: Props) {
  const { filter: f, collapsed = false } = props;

  if (collapsed) {
    return (
      <div className="h-full w-[72px] border-r bg-background flex flex-col items-center py-3">
        <div className="text-xs opacity-70 writing-vertical">Library</div>
      </div>
    );
  }

  return (
    <div className="h-full w-[320px] border-r bg-background flex flex-col">
      <div className="p-3 border-b">
        <div className="font-semibold mb-2">Library</div>

        {/* Search input */}
        <input
          className="w-full border rounded px-2 py-1 text-sm"
          placeholder="Search title, tag, owner..."
          value={f.q}
          onChange={(e) => props.onChange({ ...f, q: e.target.value })}
        />

        {/* Filter dropdowns */}
        <div className="grid grid-cols-2 gap-2 mt-2">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={f.status || ""}
            onChange={(e) =>
              props.onChange({ ...f, status: e.target.value || undefined })
            }
          >
            <option value="">Status</option>
            <option value="draft">Draft</option>
            <option value="in_review">In Review</option>
            <option value="approved">Approved</option>
            <option value="archived">Archived</option>
          </select>

          <select
            className="border rounded px-2 py-1 text-sm"
            value={f.preset || ""}
            onChange={(e) =>
              props.onChange({ ...f, preset: e.target.value || undefined })
            }
          >
            <option value="">Preset</option>
            <option value="youtube_16_9">YouTube 16:9</option>
            <option value="shorts_9_16">Shorts 9:16</option>
            <option value="slides_16_9">Slides 16:9</option>
          </select>

          {/* Content rating filter - NSFW governance */}
          <select
            className="border rounded px-2 py-1 text-sm col-span-2"
            value={f.contentRating || ""}
            onChange={(e) =>
              props.onChange({ ...f, contentRating: e.target.value || undefined })
            }
          >
            <option value="">Content Rating</option>
            <option value="sfw">SFW only</option>
            <option value="mature">Mature allowed</option>
          </select>
        </div>
      </div>

      {/* Video list slot */}
      <div className="flex-1 overflow-auto">{props.children}</div>
    </div>
  );
}
