import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Shell } from "./components/Shell";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { SpokeMap } from "./graph/SpokeMap";
import { Settings } from "./pages/Settings";
import { lazy, Suspense } from "react";
import { Manual } from "./pages/Manual";
import { PayloadSchemas } from "./pages/PayloadSchemas";
import { Designer } from "./pages/designer/Designer";
import { Visualization } from "./pages/Visualization";

// mqtt.js is heavy; keep it out of the main bundle — only load it on /live.
const LiveView = lazy(() => import("./pages/LiveView").then((m) => ({ default: m.LiveView })));

export default function App() {
  const location = useLocation();
  return (
    <Shell>
      <ErrorBoundary resetKey={location.pathname}>
        <Routes>
          <Route path="/" element={<SpokeMap />} />
          <Route path="/uns" element={<Designer />} />
          <Route path="/viz" element={<Visualization />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/payload-schemas" element={<PayloadSchemas />} />
          <Route
            path="/live"
            element={
              <Suspense fallback={<div className="grid h-full place-items-center text-sm text-fg-muted">Loading…</div>}>
                <LiveView />
              </Suspense>
            }
          />
          <Route path="/manual" element={<Manual />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </Shell>
  );
}
