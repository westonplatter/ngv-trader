# User Preferences & Privacy Mode

## Overview

A generic key-value user preferences system backed by a `user_preferences` table. The first preference built on top of it is **privacy mode**, which masks sensitive numeric values in the frontend.

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
- **Masking**: When enabled, sensitive fields (quantities, perm IDs, exec IDs, position sizes) are replaced with `"•••"` (`PRIVACY_MASK` from `frontend/src/utils/privacy.ts`).
- **Affected components**: `OrdersTable`, `OrdersSideTable`, `TradesTable`, `PositionsTable`.
