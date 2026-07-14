# User Preferences & Privacy Mode

## Overview

A generic key-value user preferences system backed by a `user_preferences` table. The first preference built on top of it is **privacy mode**, which hides sensitive numeric values in the frontend so holdings, trades, and strategies can be shown to others — revealing only *what* is held (contract types) and *relative* performance, never dollar amounts or position sizes.

## Backend

- **Model**: `UserPreference` in `src/models.py` — stores `key` (unique string) and `value` (JSON).
- **Migration**: `alembic/versions/20260227130000_add_user_preferences.py`
- **API** (`src/api/routers/user_preferences.py`):
  - `GET /api/v1/user-preferences` — list all preferences
  - `GET /api/v1/user-preferences/{key}` — get one
  - `PUT /api/v1/user-preferences/{key}` — upsert (create or update)
  - `DELETE /api/v1/user-preferences/{key}` — delete

## Frontend — Privacy Mode

- **Context**: `PrivacyContext` (`frontend/src/contexts/PrivacyContext.tsx`) provides `privacyMode` (boolean) and `togglePrivacy()` to the component tree via `PrivacyProvider`.
- **Toggle**: A button in the top nav bar reads the `privacy_mode` preference on load and persists changes via `PUT`.
- **Masking**: When enabled, sensitive fields are replaced with `"•••"` (`PRIVACY_MASK` from `frontend/src/utils/privacy.ts`):
  - **Dollar amounts** — avg cost, mark / live mark price, position value, trade execution price, order limit price, order avg fill price.
  - **Quantities** — position size, trade/order quantity, filled quantity.
  - **Identifiers** — perm IDs, exec IDs.
- **Relative returns**: P&L is *not* masked — it is re-expressed as a percentage return (`formatRelativeReturn` in `privacy.ts`): `P&L ÷ |cost basis|`. Positions derive cost basis as `position_value − fifo_pnl_unrealized`, so no dollar figure leaks; the Unrealized / Live PnL header totals use the aggregate basis. Where a reliable per-row basis isn't available (e.g. individual trade executions), the P&L stays masked rather than showing a misleading percentage.
- **Kept visible**: position *type* fields — symbol, sec type, contract, side, call/put, strike, expiry — since they describe the position, not its size or value.
- **Affected components**: `OrdersTable`, `OrdersSideTable`, `TradesTable`, `PositionsTable`, `TradeTaggingPage`.
