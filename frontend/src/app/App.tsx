import { Navigate, Route, Routes } from "react-router";

import { WorkspacePage } from "../pages/WorkspacePage";
import { CanvasPage } from "../pages/CanvasPage";
import { ReportPage } from "../pages/ReportPage";

export function App() {
  return (
    <Routes>
      <Route path="/workspace" element={<WorkspacePage />} />
      <Route path="/canvas" element={<CanvasPage />} />
      <Route path="/report" element={<ReportPage />} />
      <Route path="/slides" element={<ReportPage slides />} />
      <Route path="*" element={<Navigate to="/workspace" replace />} />
    </Routes>
  );
}
