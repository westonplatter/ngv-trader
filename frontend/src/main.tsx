import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App.tsx";
import { isDemoMode } from "./lib/demoMode";
import { installDemoApi } from "./lib/demoApi";

// In demo mode, serve the UI from static fixtures instead of a live backend.
// Installed before render so the very first request is intercepted.
if (isDemoMode()) {
  installDemoApi();
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
