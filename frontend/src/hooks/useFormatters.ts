// Money, quantity, percent and P&L formatters that already honor privacy mode.
// Components call `fmt.money(x)` instead of branching on `privacyMode`.

import { useMemo } from "react";
import { usePrivacy } from "../contexts/usePrivacy";
import { makeFormatters, type Formatters } from "../utils/maskedFormatters";

export function useFormatters(): Formatters {
  const { privacyMode } = usePrivacy();
  return useMemo(() => makeFormatters(privacyMode), [privacyMode]);
}
