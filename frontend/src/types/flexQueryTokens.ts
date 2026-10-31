// FlexQuery token rows from GET /flexquery-tokens. The token value itself
// never leaves the database; only its label and usage metadata are listed.

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

