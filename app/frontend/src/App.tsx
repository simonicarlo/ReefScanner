import { useQueryClient } from "@tanstack/react-query";
import { Route, Routes } from "react-router-dom";
import { useJobProgressSocket } from "./lib/queries";
import { Projects } from "./pages/Projects";
import { ProjectDetail } from "./pages/ProjectDetail";
import { JobDetail } from "./pages/JobDetail";
import { EventReview } from "./pages/EventReview";
import { Settings } from "./pages/Settings";
import { AppShell } from "./components/AppShell";
import { useApplyAppearance } from "./lib/appearance";

export default function App() {
  const queryClient = useQueryClient();
  // One socket for the whole app; it writes progress into the query cache.
  useJobProgressSocket(queryClient);
  useApplyAppearance();

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route path="/projects/:projectId" element={<ProjectDetail />} />
        <Route path="/jobs/:jobId" element={<JobDetail />} />
        <Route path="/jobs/:jobId/events/:eventId" element={<EventReview />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </AppShell>
  );
}
