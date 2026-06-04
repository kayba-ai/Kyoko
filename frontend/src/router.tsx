import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RunsPage } from "./pages/RunsPage";
import { McpLogPage } from "./pages/McpLogPage";
import { ProposalsPage } from "./pages/ProposalsPage";
import { IssuesPage } from "./pages/IssuesPage";
import { AutonomyPage } from "./pages/AutonomyPage";
import { ChecksPage } from "./pages/ChecksPage";
import { SettingsPage } from "./pages/SettingsPage";
import { OverviewPage } from "./pages/OverviewPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/runs" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "runs", element: <RunsPage /> },
      { path: "runs/:runId", element: <RunsPage /> },
      { path: "runs/:runId/span/:spanId", element: <RunsPage /> },
      { path: "mcp-log", element: <McpLogPage /> },
      { path: "proposals", element: <ProposalsPage /> },
      { path: "issues", element: <IssuesPage /> },
      { path: "autonomy", element: <AutonomyPage /> },
      { path: "checks", element: <ChecksPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/runs" replace /> },
    ],
  },
]);
