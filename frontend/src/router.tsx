import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { TracesPage } from "./pages/TracesPage";
import { TraceDetailPage } from "./pages/TraceDetailPage";
import { ProposalsPage } from "./pages/ProposalsPage";
import { IssuesPage } from "./pages/IssuesPage";
import { AnalysisPage } from "./pages/AnalysisPage";
import { ChecksPage } from "./pages/ChecksPage";
import { DetectorsPage } from "./pages/DetectorsPage";
import { JudgesPage } from "./pages/JudgesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { OverviewPage } from "./pages/OverviewPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/traces" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "traces", element: <TracesPage /> },
      { path: "traces/:traceId", element: <TraceDetailPage /> },
      { path: "traces/:traceId/span/:spanId", element: <TraceDetailPage /> },
      { path: "mcp-log", element: <Navigate to="/settings/agent-kyoko" replace /> },
      { path: "analysis", element: <AnalysisPage /> },
      { path: "proposals", element: <ProposalsPage /> },
      { path: "issues", element: <IssuesPage /> },
      { path: "autonomy", element: <Navigate to="/settings/autonomy" replace /> },
      { path: "checks", element: <ChecksPage /> },
      { path: "detectors", element: <DetectorsPage /> },
      { path: "judges", element: <JudgesPage /> },
      { path: "evaluation", element: <Navigate to="/detectors" replace /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "settings/autonomy", element: <SettingsPage /> },
      { path: "settings/agent-kyoko", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/traces" replace /> },
    ],
  },
]);
