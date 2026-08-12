// IBKR FlexQuery trade codes (the trade `notes` attribute) and their meanings.
// Codes arrive semicolon-delimited (e.g. "A;P"); unknown codes pass through
// unexpanded. Shared by the Trades page and the Trade Group trades table.

// Labels verbatim from IBKR's official legend:
// https://www.ibkrguides.com/reportingreference/reportguide/codes_flex.htm
// Note the three distinct dividend/investment codes: R (dividend reinvestment),
// RI (recurring investment — scheduled auto-invest), Ri (reimbursement).
export const IB_CODE_LABEL: Record<string, string> = {
  A: "Assignment",
  Ep: "Resulted from an expired position",
  Ex: "Exercise",
  O: "Opening trade",
  C: "Closing trade",
  P: "Partial execution",
  R: "Dividend reinvestment",
  RI: "Recurring investment",
  Ri: "Reimbursement",
  L: "Ordered by IB (margin violation)",
  LD: "Adjusted by loss disallowed from wash sale",
  IA: "Executed against an IB affiliate",
  SL: "Specific-lot tax lot-matching",
  LT: "Long-term P/L",
  ST: "Short-term P/L",
  Co: "Corrected trade",
  Ca: "Cancelled",
  Re: "Interest or dividend accrual reversal",
};

export function parseIbCodes(codes: string): { code: string; label: string }[] {
  return codes
    .split(";")
    .map((c) => c.trim())
    .filter(Boolean)
    .map((code) => ({ code, label: IB_CODE_LABEL[code] ?? "unknown code" }));
}

// Newline-joined "CODE — label" text for a native `title` tooltip fallback.
export function ibCodesTitle(codes: string): string {
  return parseIbCodes(codes)
    .map(({ code, label }) => `${code} — ${label}`)
    .join("\n");
}
