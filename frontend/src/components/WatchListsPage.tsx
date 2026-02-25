import { useCallback, useEffect, useState } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

const API_BASE = "http://localhost:8000/api/v1";

interface WatchListSummary {
  id: number;
  name: string;
  description: string | null;
  position: number;
  instrument_count: number;
  created_at: string;
  updated_at: string;
}

interface Instrument {
  id: number;
  watch_list_id: number;
  con_id: number;
  symbol: string;
  sec_type: string;
  exchange: string;
  currency: string;
  local_symbol: string | null;
  trading_class: string | null;
  contract_month: string | null;
  contract_expiry: string | null;
  multiplier: string | null;
  strike: number | null;
  right: string | null;
  primary_exchange: string | null;
  bid_price: number | null;
  ask_price: number | null;
  close_price: number | null;
  quote_as_of: string | null;
  contract_display_name: string;
  created_at: string;
}

interface WatchListDetail {
  id: number;
  name: string;
  description: string | null;
  instruments: Instrument[];
  created_at: string;
  updated_at: string;
}

interface WatchListQuotesRefreshResponse {
  queued: boolean;
  job_id: number | null;
  message: string;
}

const INSTRUMENT_COLUMNS: {
  key: keyof Instrument;
  label: string;
  muted?: boolean;
}[] = [
  { key: "contract_display_name", label: "Contract" },
  { key: "bid_price", label: "Bid" },
  { key: "ask_price", label: "Ask" },
  { key: "close_price", label: "Close" },
  { key: "strike", label: "Strike" },
  { key: "contract_expiry", label: "Expiry" },
  { key: "right", label: "Call/Put" },
  { key: "contract_month", label: "Month", muted: true },
  { key: "local_symbol", label: "Local Symbol", muted: true },
  { key: "sec_type", label: "Type", muted: true },
  { key: "con_id", label: "Con ID", muted: true },
  { key: "exchange", label: "Exchange", muted: true },
  { key: "multiplier", label: "Multiplier", muted: true },
];

function formatExpiry(value: string | null | undefined): string {
  if (!value) return "\u2014";
  // YYYYMMDD → YYYY-MM-DD
  if (value.length === 8 && !value.includes("-")) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

function formatQuotePrice(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "\u2014";
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function SortableWatchListItem({
  wl,
  isSelected,
  onSelect,
}: {
  wl: WatchListSummary;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: wl.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      onClick={onSelect}
      className={`flex items-center justify-between p-2 rounded cursor-pointer text-sm ${
        isSelected
          ? "bg-blue-100 border border-blue-300"
          : "hover:bg-gray-100 border border-transparent"
      }`}
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span
          {...attributes}
          {...listeners}
          className="cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600 select-none"
          onClick={(e) => e.stopPropagation()}
        >
          &#x2807;
        </span>
        <div className="min-w-0">
          <div className="font-medium truncate">{wl.name}</div>
          <div className="text-gray-400 text-xs">
            {wl.instrument_count} instrument
            {wl.instrument_count !== 1 ? "s" : ""}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function WatchListsPage() {
  const [lists, setLists] = useState<WatchListSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<WatchListDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);

  // Edit form
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [removeConfirmId, setRemoveConfirmId] = useState<number | null>(null);
  const [removingInstrumentId, setRemovingInstrumentId] = useState<
    number | null
  >(null);
  const [refreshingQuotes, setRefreshingQuotes] = useState(false);
  const [quotesRefreshMessage, setQuotesRefreshMessage] = useState<
    string | null
  >(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const fetchLists = useCallback(() => {
    fetch(`${API_BASE}/watch-lists`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: WatchListSummary[]) => {
        setLists(data);
        // Auto-select first watch list if none selected
        setSelectedId((prev) => {
          if (prev === null && data.length > 0) return data[0].id;
          return prev;
        });
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const fetchDetail = useCallback((id: number) => {
    fetch(`${API_BASE}/watch-lists/${id}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setDetail)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    fetchLists();
  }, [fetchLists]);

  // Poll detail every 5s
  useEffect(() => {
    if (selectedId === null) return;
    setQuotesRefreshMessage(null);
    fetchDetail(selectedId);
    const interval = setInterval(() => {
      fetchDetail(selectedId);
    }, 5000);
    return () => clearInterval(interval);
  }, [selectedId, fetchDetail]);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = lists.findIndex((wl) => wl.id === active.id);
    const newIndex = lists.findIndex((wl) => wl.id === over.id);
    const reordered = arrayMove(lists, oldIndex, newIndex);

    // Optimistic update
    setLists(reordered);

    // Persist to backend
    fetch(`${API_BASE}/watch-lists/reorder`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: reordered.map((wl) => wl.id) }),
    }).catch((err) => {
      setError(err.message);
      // Revert on failure
      fetchLists();
    });
  };

  const handleCreate = () => {
    if (!newName.trim()) return;
    setCreating(true);
    fetch(`${API_BASE}/watch-lists`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: newName.trim(),
        description: newDesc.trim() || null,
      }),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((created) => {
        setNewName("");
        setNewDesc("");
        fetchLists();
        setSelectedId(created.id);
      })
      .catch((err) => setError(err.message))
      .finally(() => setCreating(false));
  };

  const handleDelete = (id: number) => {
    if (!confirm("Delete this watch list and all its instruments?")) return;
    fetch(`${API_BASE}/watch-lists/${id}`, { method: "DELETE" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (selectedId === id) {
          setSelectedId(null);
          setDetail(null);
        }
        fetchLists();
      })
      .catch((err) => setError(err.message));
  };

  const startEditing = (
    id: number,
    name: string,
    description: string | null,
  ) => {
    setEditingId(id);
    setEditName(name);
    setEditDesc(description ?? "");
  };

  const handleEditSave = (id: number) => {
    if (!editName.trim()) return;
    fetch(`${API_BASE}/watch-lists/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: editName.trim(),
        description: editDesc.trim() || null,
      }),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setEditingId(null);
        fetchLists();
        if (selectedId === id) fetchDetail(id);
      })
      .catch((err) => setError(err.message));
  };

  const handleRemoveInstrumentRequest = (instrumentId: number) => {
    setRemoveConfirmId((currentId) =>
      currentId === instrumentId ? null : instrumentId,
    );
  };

  const handleRemoveInstrumentConfirm = (instrumentId: number) => {
    if (selectedId === null) return;
    setRemovingInstrumentId(instrumentId);
    fetch(`${API_BASE}/watch-lists/${selectedId}/instruments/${instrumentId}`, {
      method: "DELETE",
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setRemoveConfirmId(null);
        fetchDetail(selectedId);
        fetchLists();
      })
      .catch((err) => setError(err.message))
      .finally(() => setRemovingInstrumentId(null));
  };

  const handleRefreshQuotes = () => {
    if (selectedId === null) return;
    setRefreshingQuotes(true);
    setQuotesRefreshMessage(null);
    fetch(`${API_BASE}/watch-lists/${selectedId}/quotes/refresh`, {
      method: "POST",
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: WatchListQuotesRefreshResponse) => {
        setQuotesRefreshMessage(data.message);
        fetchDetail(selectedId);
      })
      .catch((err) => setError(err.message))
      .finally(() => setRefreshingQuotes(false));
  };

  if (loading) return <p className="text-gray-500">Loading watch lists...</p>;
  if (error) return <p className="text-red-600">Error: {error}</p>;

  return (
    <div className="flex gap-6 h-full">
      {/* Left panel: list of watch lists */}
      <div className="w-72 shrink-0 flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Watch Lists</h2>

        {/* List */}
        <div className="flex flex-col divide-y divide-gray-200 overflow-y-auto border border-gray-200 rounded">
          {lists.length === 0 && (
            <p className="text-gray-400 text-sm">No watch lists yet.</p>
          )}
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={lists.map((wl) => wl.id)}
              strategy={verticalListSortingStrategy}
            >
              {lists.map((wl) => (
                <SortableWatchListItem
                  key={wl.id}
                  wl={wl}
                  isSelected={selectedId === wl.id}
                  onSelect={() => setSelectedId(wl.id)}
                />
              ))}
            </SortableContext>
          </DndContext>
        </div>

        {/* Create form */}
        <div className="flex flex-col gap-2 p-3 border border-gray-200 rounded bg-gray-50">
          <input
            type="text"
            placeholder="Name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <button
            onClick={handleCreate}
            disabled={creating || !newName.trim()}
            className="bg-blue-600 text-white text-sm px-3 py-1 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {creating ? "Creating..." : "Create"}
          </button>
        </div>
      </div>

      {/* Right panel: instruments table */}
      <div className="flex-1 min-w-0">
        {detail === null ? (
          <p className="text-gray-400 mt-8">
            Select a watch list to view instruments.
          </p>
        ) : (
          <>
            {editingId === detail.id ? (
              <div className="flex flex-col gap-2 mb-4 max-w-md">
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1 text-sm"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleEditSave(detail.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                  autoFocus
                />
                <input
                  type="text"
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  placeholder="Description (optional)"
                  className="border border-gray-300 rounded px-2 py-1 text-sm"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleEditSave(detail.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => handleEditSave(detail.id)}
                    disabled={!editName.trim()}
                    className="rounded border border-blue-300 px-1.5 py-0.5 text-[11px] text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => setEditingId(null)}
                    className="rounded border border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-700 hover:bg-gray-100"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="mb-4 flex items-center gap-3">
                <h2 className="text-lg font-semibold">{detail.name}</h2>
                {detail.description && (
                  <span className="text-gray-400 text-sm">
                    {detail.description}
                  </span>
                )}
                <div className="flex gap-1">
                  <button
                    onClick={handleRefreshQuotes}
                    disabled={
                      refreshingQuotes || detail.instruments.length === 0
                    }
                    className="rounded border border-emerald-300 px-1.5 py-0.5 text-[11px] text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                  >
                    {refreshingQuotes ? "Refreshing..." : "Refresh Quotes"}
                  </button>
                  <button
                    onClick={() =>
                      startEditing(detail.id, detail.name, detail.description)
                    }
                    className="rounded border border-blue-300 px-1.5 py-0.5 text-[11px] text-blue-700 hover:bg-blue-50"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => handleDelete(detail.id)}
                    className="rounded border border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-700 hover:bg-gray-100"
                  >
                    Delete
                  </button>
                </div>
              </div>
            )}
            {quotesRefreshMessage && (
              <p className="mb-3 text-xs text-gray-600">
                {quotesRefreshMessage}
              </p>
            )}
            {detail.instruments.length === 0 ? (
              <p className="text-gray-400 text-sm">
                No instruments yet. Add some via the Tradebot chat.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead>
                    <tr className="bg-gray-100 text-left">
                      {INSTRUMENT_COLUMNS.map((col) => (
                        <th
                          key={col.key}
                          className={`px-3 py-2 font-semibold whitespace-nowrap ${col.muted ? "text-gray-400 font-normal" : "text-gray-700"}`}
                        >
                          {col.label}
                        </th>
                      ))}
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {detail.instruments.map((inst) => (
                      <tr
                        key={inst.id}
                        className="border-b border-gray-200 hover:bg-gray-50"
                      >
                        {INSTRUMENT_COLUMNS.map((col) => (
                          <td
                            key={col.key}
                            className={`px-3 py-2 whitespace-nowrap ${col.muted ? "text-gray-400" : ""}`}
                          >
                            {col.key === "bid_price" ||
                            col.key === "ask_price" ||
                            col.key === "close_price"
                              ? formatQuotePrice(inst[col.key] as number | null)
                              : col.key === "contract_expiry"
                                ? formatExpiry(inst[col.key] as string | null)
                                : (inst[col.key] ?? "\u2014")}
                          </td>
                        ))}
                        <td className="px-3 py-2">
                          <div className="flex gap-1">
                            <button
                              onClick={() =>
                                handleRemoveInstrumentRequest(inst.id)
                              }
                              className="rounded border border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-700 hover:bg-gray-100"
                            >
                              Remove
                            </button>
                            {removeConfirmId === inst.id && (
                              <button
                                onClick={() =>
                                  handleRemoveInstrumentConfirm(inst.id)
                                }
                                disabled={removingInstrumentId === inst.id}
                                className="rounded border border-red-600 bg-red-600 px-1.5 py-0.5 text-[11px] text-white hover:bg-red-700 disabled:opacity-50"
                              >
                                Confirm
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
