// Singleton EventSource client. A single SSE connection is shared across all
// React components in the tab, keyed by the union of all subscribed topics.
// When a new topic is subscribed that was not in the original connection URL,
// the connection is closed and reopened with the full topic list.

import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../config";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

type Callback<T = unknown> = (payload: T, eventType: string) => void;

// SSE event envelope emitted by the backend (src/services/ui_events.py UIEvent).
interface SSEEnvelope {
  topic: string;
  event: string;
  entity_id: number | null;
  occurred_at: string;
  version: number;
  payload: unknown;
}

// All named SSE event types the backend sets via the SSE `event:` field.
// EventSource.onmessage only fires for unnamed events; named events require
// explicit addEventListener calls.
const KNOWN_SSE_EVENTS = [
  "job.created",
  "job.updated",
  "job.archived",
  "order.created",
  "order.updated",
  "order.cancelled",
  "worker.heartbeat",
  "trades.changed",
  "positions.changed",
] as const;

// ─── Singleton state ─────────────────────────────────────────────────────────

const subscribers = new Map<string, Set<Callback>>();
const statusListeners = new Set<(s: ConnectionStatus) => void>();
let es: EventSource | null = null;
let openedTopics: ReadonlySet<string> = new Set();
let currentStatus: ConnectionStatus = "disconnected";

function notifyStatus(s: ConnectionStatus): void {
  currentStatus = s;
  for (const fn of statusListeners) fn(s);
}

function handleEnvelope(data: string): void {
  try {
    const envelope = JSON.parse(data) as SSEEnvelope;
    subscribers
      .get(envelope.topic)
      ?.forEach((cb) => cb(envelope.payload, envelope.event));
  } catch {
    // ignore malformed event data
  }
}

function buildUrl(topics: ReadonlySet<string>): string {
  const sorted = [...topics].sort().join(",");
  return `${API_BASE_URL}/events/stream?topics=${encodeURIComponent(sorted)}`;
}

function openConnection(topics: ReadonlySet<string>): void {
  es?.close();
  openedTopics = new Set(topics);

  if (topics.size === 0) {
    es = null;
    notifyStatus("disconnected");
    return;
  }

  const handler = (e: MessageEvent<string>) => handleEnvelope(e.data);
  const source = new EventSource(buildUrl(topics));
  es = source;
  notifyStatus("connecting");

  source.onopen = () => notifyStatus("connected");
  source.onerror = () => notifyStatus("disconnected");

  for (const eventType of KNOWN_SSE_EVENTS) {
    source.addEventListener(eventType, handler as EventListener);
  }
  // Fallback for any events sent without an explicit SSE event: field.
  source.onmessage = handler;
}

function currentTopics(): Set<string> {
  return new Set(subscribers.keys());
}

function totalCallbacks(): number {
  let n = 0;
  for (const s of subscribers.values()) n += s.size;
  return n;
}

function subscribeCallback<T>(topic: string, cb: Callback<T>): void {
  if (!subscribers.has(topic)) subscribers.set(topic, new Set());
  subscribers.get(topic)!.add(cb as Callback);

  const needsNew = es === null || !openedTopics.has(topic);
  if (needsNew) openConnection(currentTopics());
}

function unsubscribeCallback<T>(topic: string, cb: Callback<T>): void {
  subscribers.get(topic)?.delete(cb as Callback);
  if (subscribers.get(topic)?.size === 0) subscribers.delete(topic);

  if (totalCallbacks() === 0) {
    es?.close();
    es = null;
    openedTopics = new Set();
    notifyStatus("disconnected");
  }
}

// ─── React hook ──────────────────────────────────────────────────────────────

export function useSSE<T>(
  topic: string,
  onEvent: (payload: T, eventType: string) => void,
): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>(currentStatus);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const statusListener = (s: ConnectionStatus) => setStatus(s);
    statusListeners.add(statusListener);

    // Stable wrapper so subscribe and unsubscribe use the same reference.
    const cb: Callback = (payload, eventType) =>
      onEventRef.current(payload as T, eventType);
    subscribeCallback<T>(topic, cb as Callback<T>);

    return () => {
      statusListeners.delete(statusListener);
      unsubscribeCallback<T>(topic, cb as Callback<T>);
    };
  }, [topic]);

  return status;
}
