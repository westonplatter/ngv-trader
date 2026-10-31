// Job queue payloads. Mirrors JobResponse in src/api/routers/jobs.py; the same
// shape arrives over SSE on the "jobs" topic.

export interface Job {
  id: number;
  job_type: string;
  status: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  source: string;
  request_text: string | null;
  attempts: number;
  max_attempts: number;
  available_at: string;
  started_at: string | null;
  completed_at: string | null;
  archived_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}
