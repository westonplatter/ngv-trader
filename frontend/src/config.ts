/**
 * Central configuration for the frontend.
 *
 * The API base URL defaults to http://localhost:8000/api/v1 during
 * development.  Override it by setting VITE_API_BASE_URL in a
 * frontend/.env file or in your shell environment.
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
