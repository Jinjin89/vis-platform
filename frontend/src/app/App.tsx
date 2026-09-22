import { Navigate, Route, Routes } from "react-router";

import { WorkspacePage } from "../pages/WorkspacePage";
import { CanvasPage } from "../pages/CanvasPage";
import { ReportPage } from "../pages/ReportPage";
import { PinpointPage } from "../pages/PinpointPage";

export function App() {
  return (
    <Routes>
      <Route path="/workspace" element={<WorkspacePage />} />
      <Route path="/canvas" element={<CanvasPage />} />
      <Route path="/report" element={<ReportPage />} />
      <Route path="/slides" element={<ReportPage format="slides" />} />
      <Route path="/figure" element={<ReportPage format="figure" />} />
      <Route path="/pinpoint" element={<PinpointPage />} />
      <Route path="*" element={<Navigate to="/workspace" replace />} />
    </Routes>
  );
}
