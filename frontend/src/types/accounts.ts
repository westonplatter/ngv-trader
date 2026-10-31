// IBKR account rows. Mirrors AccountResponse in src/api/routers/accounts.py.
// `account` is the raw id and is only rendered behind an explicit reveal.

export interface Account {
  id: number;
  account: string;
  masked_account: string;
  alias: string | null;
  flex_query_token_id: number | null;
  flex_query_token_name: string | null;
}
