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
import { PlcSimulators } from "./pages/PlcSimulators";
import { Start } from "./pages/Start";
import { isOnboarded } from "./onboarding";

// mqtt.js is heavy; keep it out of the main bundle — only load it on /live.
const LiveView = lazy(() => import("./pages/LiveView").then((m) => ({ default: m.LiveView })));

// First-visit gate for "/". A component (not an inline ternary in the route
// element) so isOnboarded() is re-read every time the route mounts — an inline
// ternary is evaluated once at App render and froze "/" to a redirect, breaking
// the UNS Hub menu entry after finishing the wizard.
let autoStarted = false;
function HomeGate() {
  // Open the Quick-start once for a brand-new visitor (no onboarded flag yet),
  // on the first navigation of this page load. NOT a hard gate: autoStarted
  // latches immediately, so "/" then always renders home and other menu items
  // are never bounced back to the wizard. Skip/Finish (markOnboarded) stops it
  // re-opening on later loads.
  if (!autoStarted) {
    autoStarted = true;
    if (!isOnboarded()) return <Navigate to="/start" replace />;
  }
  return <SpokeMap />;
}

export default function App() {
  const location = useLocation();
  return (
    <Shell>
      <ErrorBoundary resetKey={location.pathname}>
        <Routes>
          <Route path="/" element={<HomeGate />} />
          <Route path="/start" element={<Start />} />
          <Route path="/uns" element={<Designer />} />
          <Route path="/viz" element={<Visualization />} />
          <Route path="/plc" element={<PlcSimulators />} />
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
