// Strategy rows from GET /strategies.

export type Strategy = {
  id: number;
  name: string;
  normalized_name: string;
  created_by: string;
  created_at: string;
  archived_at: string | null;
};
