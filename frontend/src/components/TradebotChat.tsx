import { useMemo, useState } from "react";
import { useChat } from "@ai-sdk/react";
import { TextStreamChatTransport, type UIMessage } from "ai";
import JobsTable from "./JobsTable";

const QUICK_PROMPTS = [
  "Show me current positions",
  "Show CL front-month contracts",
  "Show my watch lists",
];
const POSITION_SYNC_PROMPT = "Refresh positions now";

function messageText(message: UIMessage): string {
  const parts = message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text.trim())
    .filter((text) => text.length > 0);
  return parts.join("\n");
}

function sanitizeOutboundText(text: string): string {
  const withRedactedIbAccounts = text.replace(
    /\b[DdUuFf][a-zA-Z0-9]{6,}\b/g,
    "[redacted-account]",
  );
  return withRedactedIbAccounts.trim() || "[redacted]";
}

export default function TradebotChat() {
  const transport = useMemo(
    () =>
      new TextStreamChatTransport({
        api: "http://localhost:8000/api/v1/tradebot/chat",
        prepareSendMessagesRequest: ({ id, messages, trigger, messageId }) => {
          const outboundMessages = messages
            .map((message) => {
              const text = messageText(message);
              if (!text) return null;
              return {
                role: message.role,
                parts: [
                  {
                    type: "text",
                    text:
                      message.role === "user"
                        ? sanitizeOutboundText(text)
                        : text,
                  },
                ],
              };
            })
            .filter(
              (message): message is Exclude<typeof message, null> =>
                message !== null,
            );
          return {
            body: {
              id,
              messages: outboundMessages,
              trigger,
              messageId,
            },
          };
        },
      }),
    [],
  );
  const { messages, sendMessage, status, error, stop } = useChat({ transport });
  const [input, setInput] = useState("");

  const submit = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    try {
      await sendMessage({ text: trimmed });
    } finally {
      setInput("");
    }
  };

  return (
    <div className="w-full h-full min-h-0 overflow-y-auto lg:overflow-hidden">
      <div className="grid h-auto min-h-0 gap-4 lg:h-full lg:overflow-hidden lg:grid-cols-[minmax(0,3fr)_minmax(400px,2fr)]">
        <div className="min-w-0 min-h-0 lg:h-full flex flex-col">
          <div className="mb-3 flex flex-wrap gap-2">
            <button
              onClick={() => void submit(POSITION_SYNC_PROMPT)}
              disabled={status === "submitted" || status === "streaming"}
              className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Kickoff Position Sync
            </button>
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                onClick={() => setInput(prompt)}
                className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
              >
                {prompt}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto rounded border border-gray-300 bg-white p-4">
            {messages.length === 0 && (
              <p className="text-sm text-gray-500">
                Ask about positions, contracts, watch lists, or jobs.
              </p>
            )}
            <div className="space-y-3">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className="rounded border border-gray-200 p-3 text-sm"
                >
                  <p className="mb-1 text-xs uppercase tracking-wide text-gray-500">
                    {message.role}
                  </p>
                  <pre className="whitespace-pre-wrap font-sans text-gray-900">
                    {messageText(message) || "…"}
                  </pre>
                </div>
              ))}
            </div>
          </div>

          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void submit(input);
            }}
          >
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="e.g. show CL front month"
              className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
            />
            <button
              type="submit"
              disabled={status === "submitted" || status === "streaming"}
              className="rounded bg-black px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              Send
            </button>
            {(status === "submitted" || status === "streaming") && (
              <button
                type="button"
                onClick={() => stop()}
                className="rounded border border-gray-300 px-3 py-2 text-sm text-gray-700"
              >
                Stop
              </button>
            )}
          </form>

          <p className="mt-2 text-xs text-gray-500">Status: {status}</p>
          {error && (
            <p className="mt-1 text-xs text-red-600">Error: {error.message}</p>
          )}
        </div>
        <JobsTable />
      </div>
    </div>
  );
}
