import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { TracesPage } from "./pages/TracesPage";
import { TraceDetailPage } from "./pages/TraceDetailPage";
import { McpLogPage } from "./pages/McpLogPage";
import { ProposalsPage } from "./pages/ProposalsPage";
import { IssuesPage } from "./pages/IssuesPage";
import { AutonomyPage } from "./pages/AutonomyPage";
import { AnalysisPage } from "./pages/AnalysisPage";
import { ChecksPage } from "./pages/ChecksPage";
import { DetectorsPage } from "./pages/DetectorsPage";
import { JudgesPage } from "./pages/JudgesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SetupWizardPage } from "./pages/SetupWizardPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/setup" replace /> },
      { path: "setup", element: <SetupWizardPage /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "traces", element: <TracesPage /> },
      { path: "traces/:traceId", element: <TraceDetailPage /> },
      { path: "traces/:traceId/span/:spanId", element: <TraceDetailPage /> },
      { path: "mcp-log", element: <McpLogPage /> },
      { path: "analysis", element: <AnalysisPage /> },
      { path: "proposals", element: <ProposalsPage /> },
      { path: "issues", element: <IssuesPage /> },
      { path: "autonomy", element: <AutonomyPage /> },
      { path: "checks", element: <ChecksPage /> },
      { path: "detectors", element: <DetectorsPage /> },
      { path: "judges", element: <JudgesPage /> },
      { path: "evaluation", element: <Navigate to="/detectors" replace /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/traces" replace /> },
    ],
  },
]);
