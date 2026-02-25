import { useEffect, useState } from "react";

function CopyIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      fill="currentColor"
      className="w-4 h-4"
    >
      <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z" />
      <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      fill="currentColor"
      className="w-4 h-4"
    >
      <path
        fillRule="evenodd"
        d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function EyeIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 20 20"
      fill="currentColor"
      className="w-4 h-4"
    >
      <path
        fillRule="evenodd"
        d="M3.28 2.22a.75.75 0 00-1.06 1.06l14.5 14.5a.75.75 0 101.06-1.06l-1.745-1.745a10.029 10.029 0 003.3-4.38 1.651 1.651 0 000-1.186A10.004 10.004 0 0010 3c-1.67 0-3.248.41-4.63 1.13L3.28 2.22zM7.74 6.68a4 4 0 015.58 5.58L7.74 6.68z"
        clipRule="evenodd"
      />
      <path d="M10.748 13.93l2.523 2.523A9.987 9.987 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41a1.651 1.651 0 010-1.186 10.007 10.007 0 012.89-4.01l2.5 2.5a4 4 0 005.693 5.693z" />
    </svg>
  );
}

interface Account {
  id: number;
  account: string;
  masked_account: string;
  alias: string | null;
}

export default function AccountsTable() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [revealedAccounts, setRevealedAccounts] = useState<Set<number>>(
    new Set(),
  );
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const toggleReveal = (id: number) => {
    setRevealedAccounts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const copyAccount = (account: Account) => {
    navigator.clipboard.writeText(account.account).then(() => {
      setCopiedId(account.id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  function fetchAccounts() {
    fetch("http://localhost:8000/api/v1/accounts")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setAccounts)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchAccounts();
  }, []);

  function startEdit(account: Account) {
    setEditingId(account.id);
    setEditValue(account.alias ?? "");
  }

  function cancelEdit() {
    setEditingId(null);
    setEditValue("");
  }

  function saveAlias(id: number) {
    setSaving(true);
    const alias = editValue.trim() || null;
    fetch(`http://localhost:8000/api/v1/accounts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alias }),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((updated: Account) => {
        setAccounts((prev) =>
          prev.map((a) => (a.id === updated.id ? updated : a)),
        );
        setEditingId(null);
        setEditValue("");
      })
      .catch((err) => setError(err.message))
      .finally(() => setSaving(false));
  }

  if (loading) return <p className="text-gray-500">Loading accounts...</p>;
  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (accounts.length === 0)
    return <p className="text-gray-500">No accounts found.</p>;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-md border-collapse text-sm">
        <thead>
          <tr className="bg-gray-100 text-left">
            <th className="px-3 py-2 font-semibold text-gray-700">ID</th>
            <th className="px-3 py-2 font-semibold text-gray-700">Account</th>
            <th className="px-3 py-2 font-semibold text-gray-700">Alias</th>
            <th className="px-3 py-2 font-semibold text-gray-700">Actions</th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => (
            <tr
              key={account.id}
              className="border-b border-gray-200 hover:bg-gray-50"
            >
              <td className="px-3 py-2">{account.id}</td>
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-2">
                  <span className="font-mono">
                    {revealedAccounts.has(account.id)
                      ? account.masked_account
                      : "*".repeat(account.masked_account.length)}
                  </span>
                  <button
                    onClick={() => toggleReveal(account.id)}
                    className="text-gray-400 hover:text-gray-700"
                    title={
                      revealedAccounts.has(account.id)
                        ? "Hide last 2 digits"
                        : "Reveal last 2 digits"
                    }
                  >
                    <EyeIcon />
                  </button>
                  <button
                    onClick={() => copyAccount(account)}
                    className="text-gray-400 hover:text-gray-700"
                    title="Copy account ID"
                  >
                    {copiedId === account.id ? <CheckIcon /> : <CopyIcon />}
                  </button>
                </span>
              </td>
              <td className="px-3 py-2">
                {editingId === account.id ? (
                  <input
                    type="text"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") saveAlias(account.id);
                      if (e.key === "Escape") cancelEdit();
                    }}
                    className="border border-gray-300 rounded px-2 py-1 text-sm w-48"
                    autoFocus
                  />
                ) : (
                  <span className="text-gray-600">
                    {account.alias ?? <span className="italic">Not set</span>}
                  </span>
                )}
              </td>
              <td className="px-3 py-2">
                {editingId === account.id ? (
                  <span className="space-x-2">
                    <button
                      onClick={() => saveAlias(account.id)}
                      disabled={saving}
                      className="text-sm text-green-700 hover:underline disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={cancelEdit}
                      disabled={saving}
                      className="text-sm text-gray-500 hover:underline disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    onClick={() => startEdit(account)}
                    className="text-sm text-blue-600 hover:underline"
                  >
                    Edit
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
