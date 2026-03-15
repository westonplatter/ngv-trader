import { useEffect, useRef, useState } from "react";

export interface ComboboxOption<T = unknown> {
  label: string;
  value: string;
  data: T;
}

interface ComboboxInputProps<T> {
  options: ComboboxOption<T>[];
  value: string;
  onChange: (option: ComboboxOption<T>) => void;
  onClear?: () => void;
  placeholder?: string;
  loading?: boolean;
}

export default function ComboboxInput<T>({
  options,
  value,
  onChange,
  onClear,
  placeholder = "Search...",
  loading = false,
}: ComboboxInputProps<T>) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const safeOptions = options ?? [];
  const filtered = query
    ? safeOptions
        .filter((o) => o.label.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 50)
    : safeOptions.slice(0, 50);

  useEffect(() => {
    setHighlightIdx(0);
  }, [query]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Scroll highlighted item into view
  useEffect(() => {
    if (!open || !listRef.current) return;
    const item = listRef.current.children[highlightIdx] as HTMLElement;
    if (item) item.scrollIntoView({ block: "nearest" });
  }, [highlightIdx, open]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "Enter") {
        setOpen(true);
        e.preventDefault();
      }
      return;
    }
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightIdx((i) => Math.min(i + 1, filtered.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightIdx((i) => Math.max(i - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        if (filtered[highlightIdx]) {
          onChange(filtered[highlightIdx]);
          setQuery("");
          setOpen(false);
        }
        break;
      case "Escape":
        setOpen(false);
        break;
    }
  }

  const displayValue = open ? query : value;

  return (
    <div ref={containerRef} className="relative">
      <div className="flex items-center">
        <input
          type="text"
          value={displayValue}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="border border-gray-300 rounded px-2 py-1 text-sm w-full"
        />
        {value && onClear && (
          <button
            type="button"
            onClick={() => {
              onClear();
              setQuery("");
            }}
            className="ml-1 text-gray-400 hover:text-gray-600 text-xs"
          >
            ✕
          </button>
        )}
      </div>
      {open && (
        <ul
          ref={listRef}
          className="absolute z-50 mt-1 w-full max-h-60 overflow-auto bg-white border border-gray-200 rounded shadow-lg text-sm"
        >
          {loading && <li className="px-2 py-1.5 text-gray-400">Loading...</li>}
          {!loading && filtered.length === 0 && (
            <li className="px-2 py-1.5 text-gray-400">No matches</li>
          )}
          {!loading &&
            filtered.map((opt, i) => (
              <li
                key={opt.value}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange(opt);
                  setQuery("");
                  setOpen(false);
                }}
                onMouseEnter={() => setHighlightIdx(i)}
                className={`px-2 py-1.5 cursor-pointer ${
                  i === highlightIdx
                    ? "bg-blue-100 text-blue-900"
                    : "hover:bg-gray-50"
                }`}
              >
                {opt.label}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
