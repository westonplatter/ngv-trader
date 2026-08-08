import { useEffect, useState } from "react";
import { API_BASE_URL } from "../config";

// The token value is write-only: it is sent on create/update and never comes
// back from the API, so there is nothing here to reveal or copy.
export interface FlexQueryToken {
  id: number;
  name: string;
  report_id: string;
  is_active: boolean;
  notes: string | null;
  last_used_at: string | null;
  account_count: number;
  paused_until: string | null;
  pause_reason: string | null;
}

// How long a manual pause lasts, matching the automatic cooldown applied when
// IBKR answers 1025.
const MANUAL_PAUSE_MINUTES = 20;

// Row actions render as buttons rather than links: they perform an action on
// this page, they do not navigate.
const ACTION_BUTTON =
  "rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50";
const PRIMARY_ACTION_BUTTON =
  "rounded border border-blue-600 bg-blue-600 px-2 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50";

function pauseRemainingMinutes(token: FlexQueryToken): number {
  if (!token.paused_until) return 0;
  const remainingMs = new Date(token.paused_until).getTime() - Date.now();
  return remainingMs > 0 ? Math.ceil(remainingMs / 60000) : 0;
}

interface EditState {
  name: string;
  report_id: string;
  token: string;
}

const EMPTY_EDIT: EditState = { name: "", report_id: "", token: "" };

function formatLastUsed(value: string | null): string {
  if (!value) return "never";
  return new Date(value).toLocaleString();
}

export default function FlexQueryTokensTable() {
  const [tokens, setTokens] = useState<FlexQueryToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newToken, setNewToken] = useState<EditState>(EMPTY_EDIT);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [edit, setEdit] = useState<EditState>(EMPTY_EDIT);

  function fetchTokens() {
    fetch(`${API_BASE_URL}/flexquery-tokens`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setTokens)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchTokens();
  }, []);

  // The API returns a readable `detail` for the cases a user can cause —
  // duplicate name, unset encryption key — so surface it rather than the status.
  async function readError(res: Response): Promise<string> {
    try {
      const body = await res.json();
      return typeof body?.detail === "string"
        ? body.detail
        : `HTTP ${res.status}`;
    } catch {
      return `HTTP ${res.status}`;
    }
  }

  async function send(path: string, method: string, body: unknown) {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${path}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await readError(res));
      fetchTokens();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function createToken() {
    const ok = await send("/flexquery-tokens", "POST", {
      name: newToken.name.trim(),
      report_id: newToken.report_id.trim(),
      token: newToken.token,
    });
    if (ok) {
      setNewToken(EMPTY_EDIT);
      setAdding(false);
    }
  }

  async function saveEdit(id: number) {
    // A blank token field means "leave the stored token alone".
    const payload: Record<string, string> = {
      name: edit.name.trim(),
      report_id: edit.report_id.trim(),
    };
    if (edit.token.trim()) payload.token = edit.token;
    const ok = await send(`/flexquery-tokens/${id}`, "PATCH", payload);
    if (ok) {
      setEditingId(null);
      setEdit(EMPTY_EDIT);
    }
  }

  function toggleActive(token: FlexQueryToken) {
    send(`/flexquery-tokens/${token.id}`, "PATCH", {
      is_active: !token.is_active,
    });
  }

  // 0 minutes clears the cooldown; anything else starts one.
  function togglePause(token: FlexQueryToken) {
    send(`/flexquery-tokens/${token.id}`, "PATCH", {
      pause_minutes:
        pauseRemainingMinutes(token) > 0 ? 0 : MANUAL_PAUSE_MINUTES,
    });
  }

  function startEdit(token: FlexQueryToken) {
    setEditingId(token.id);
    setEdit({ name: token.name, report_id: token.report_id, token: "" });
  }

  const canCreate =
    newToken.name.trim() && newToken.report_id.trim() && newToken.token.trim();

  return (
    <section className="mb-8">
      <div className="mb-2 flex items-center gap-3">
        <h2 className="text-base font-semibold text-gray-800">
          IBKR FlexQuery Tokens
        </h2>
        {!adding && (
          <button onClick={() => setAdding(true)} className={ACTION_BUTTON}>
            Add token
          </button>
        )}
      </div>

      <p className="mb-3 max-w-2xl text-xs text-gray-500">
        One token can cover several IBKR accounts; each account below is stamped
        with the token it was last synced under. Token values are encrypted at
        rest and never sent back to this page — to change one, type a
        replacement.
      </p>

      {error && <p className="mb-3 text-sm text-red-600">Error: {error}</p>}

      {adding && (
        <div className="mb-3 flex flex-wrap items-end gap-2 rounded border border-gray-200 bg-gray-50 p-3">
          <label className="flex flex-col text-xs text-gray-600">
            Alias
            <input
              type="text"
              value={newToken.name}
              onChange={(e) =>
                setNewToken({ ...newToken, name: e.target.value })
              }
              placeholder="main"
              className="mt-1 w-36 rounded border border-gray-300 px-2 py-1 text-sm"
              autoFocus
            />
          </label>
          <label className="flex flex-col text-xs text-gray-600">
            Report ID
            <input
              type="text"
              value={newToken.report_id}
              onChange={(e) =>
                setNewToken({ ...newToken, report_id: e.target.value })
              }
              placeholder="633891"
              className="mt-1 w-36 rounded border border-gray-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="flex flex-col text-xs text-gray-600">
            Token
            <input
              type="password"
              value={newToken.token}
              onChange={(e) =>
                setNewToken({ ...newToken, token: e.target.value })
              }
              placeholder="from IBKR client portal"
              className="mt-1 w-64 rounded border border-gray-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            onClick={createToken}
            disabled={saving || !canCreate}
            className={PRIMARY_ACTION_BUTTON}
          >
            Save
          </button>
          <button
            onClick={() => {
              setAdding(false);
              setNewToken(EMPTY_EDIT);
            }}
            disabled={saving}
            className={ACTION_BUTTON}
          >
            Cancel
          </button>
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Loading tokens...</p>
      ) : tokens.length === 0 ? (
        <p className="text-gray-500">
          No tokens configured. Add one to enable FlexQuery sync.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-md border-collapse text-sm">
            <thead>
              <tr className="bg-gray-100 text-left">
                <th className="px-3 py-2 font-semibold text-gray-700">ID</th>
                <th className="px-3 py-2 font-semibold text-gray-700">Alias</th>
                <th className="px-3 py-2 font-semibold text-gray-700">
                  Report ID
                </th>
                <th className="px-3 py-2 font-semibold text-gray-700">Token</th>
                <th className="px-3 py-2 font-semibold text-gray-700">
                  Accounts
                </th>
                <th className="px-3 py-2 font-semibold text-gray-700">
                  Last Used
                </th>
                <th className="px-3 py-2 font-semibold text-gray-700">
                  Status
                </th>
                <th className="px-3 py-2 font-semibold text-gray-700">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((token) => (
                <tr
                  key={token.id}
                  className="border-b border-gray-200 hover:bg-gray-50"
                >
                  <td className="px-3 py-2">{token.id}</td>
                  <td className="px-3 py-2">
                    {editingId === token.id ? (
                      <input
                        type="text"
                        value={edit.name}
                        onChange={(e) =>
                          setEdit({ ...edit, name: e.target.value })
                        }
                        className="w-32 rounded border border-gray-300 px-2 py-1 text-sm"
                        autoFocus
                      />
                    ) : (
                      <span className="font-mono">{token.name}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {editingId === token.id ? (
                      <input
                        type="text"
                        value={edit.report_id}
                        onChange={(e) =>
                          setEdit({ ...edit, report_id: e.target.value })
                        }
                        className="w-32 rounded border border-gray-300 px-2 py-1 text-sm"
                      />
                    ) : (
                      token.report_id
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {editingId === token.id ? (
                      <input
                        type="password"
                        value={edit.token}
                        onChange={(e) =>
                          setEdit({ ...edit, token: e.target.value })
                        }
                        placeholder="unchanged"
                        className="w-56 rounded border border-gray-300 px-2 py-1 text-sm"
                      />
                    ) : (
                      <span className="text-gray-400 italic">encrypted</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{token.account_count}</td>
                  <td className="px-3 py-2 text-gray-600">
                    {formatLastUsed(token.last_used_at)}
                  </td>
                  <td className="px-3 py-2">
                    {!token.is_active ? (
                      <span className="inline-flex rounded bg-gray-200 px-2 py-0.5 text-xs text-gray-600">
                        inactive
                      </span>
                    ) : pauseRemainingMinutes(token) > 0 ? (
                      <span
                        className="inline-flex rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800"
                        title={
                          token.pause_reason ?? "Report fetches are held back"
                        }
                      >
                        paused {pauseRemainingMinutes(token)}m
                      </span>
                    ) : (
                      <span className="inline-flex rounded bg-green-100 px-2 py-0.5 text-xs text-green-800">
                        active
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <div className="flex gap-2">
                      {editingId === token.id ? (
                        <>
                          <button
                            onClick={() => saveEdit(token.id)}
                            disabled={saving}
                            className={PRIMARY_ACTION_BUTTON}
                          >
                            Save
                          </button>
                          <button
                            onClick={() => {
                              setEditingId(null);
                              setEdit(EMPTY_EDIT);
                            }}
                            disabled={saving}
                            className={ACTION_BUTTON}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => startEdit(token)}
                            className={ACTION_BUTTON}
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => togglePause(token)}
                            disabled={saving}
                            className={ACTION_BUTTON}
                            title={
                              pauseRemainingMinutes(token) > 0
                                ? "Resume report fetches now"
                                : `Hold report fetches for ${MANUAL_PAUSE_MINUTES} minutes`
                            }
                          >
                            {pauseRemainingMinutes(token) > 0
                              ? "Resume"
                              : "Pause"}
                          </button>
                          <button
                            onClick={() => toggleActive(token)}
                            disabled={saving}
                            className={ACTION_BUTTON}
                          >
                            {token.is_active ? "Deactivate" : "Activate"}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
