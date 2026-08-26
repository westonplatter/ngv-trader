// Top-nav configuration.
//
// Its own module (not part of App.tsx) so the invariant below is testable
// without importing the whole component tree — App pulls in plotly, which needs
// a DOM the test runner does not have.

export type NavItem = {
  label: string;
  path: string;
  // Match this path exactly instead of matching descendants too. Required on any
  // entry that is a prefix of another: without it, /strategies/table renders
  // both "Strategies" and "Strategy P&L" as the active tab, which misreports
  // where the operator is. See navItems.test.ts.
  end?: boolean;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { label: "Accounts", path: "/accounts" },
  { label: "Orders", path: "/orders" },
  { label: "Positions", path: "/positions" },
  { label: "Trades", path: "/trades" },
  { label: "Strategies", path: "/strategies", end: true },
  { label: "Strategy P&L", path: "/strategies/table" },
  { label: "Watch Lists", path: "/watchlists" },
  { label: "Market Data", path: "/market-data" },
  { label: "Structures", path: "/structures" },
  { label: "Tradebot", path: "/tradebot" },
];
