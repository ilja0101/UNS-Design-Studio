import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { I18nProvider } from "./i18n";
import { applyThemeFromStorage } from "./theme";
import "./index.css";

// Apply the persisted theme before first paint to avoid a flash.
applyThemeFromStorage();

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

// Served under /app by Quart. In AMIX governed mode the whole app is proxied
// under a portal prefix (window.__AMIX_BASE__), so the router basename becomes
// "{prefix}app"; standalone it stays "/app".
const AMIX_BASE = (window as { __AMIX_BASE__?: string }).__AMIX_BASE__;
const routerBasename = (AMIX_BASE ? AMIX_BASE.replace(/\/$/, "") : "") + "/app";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={routerBasename}>
        <I18nProvider>
          <App />
        </I18nProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
