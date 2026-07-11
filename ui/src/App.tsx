import { Routes, Route, Navigate } from "react-router-dom";
import { Shell } from "./components/Shell";
import { HubSpoke } from "./graph/HubSpoke";

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<HubSpoke />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}
