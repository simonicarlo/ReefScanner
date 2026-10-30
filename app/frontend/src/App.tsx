import { useQueryClient } from "@tanstack/react-query";
import { Route, Routes } from "react-router-dom";
import { useJobProgressSocket } from "./lib/queries";
import { Projects } from "./pages/Projects";
import { ProjectDetail } from "./pages/ProjectDetail";
import { JobDetail } from "./pages/JobDetail";
import { EventReview } from "./pages/EventReview";
import { Settings } from "./pages/Settings";
import { AppShell } from "./components/AppShell";
import { Page } from "./components/Page";
import { useApplyAppearance } from "./lib/appearance";

export default function App() {
  const queryClient = useQueryClient();
  // One socket for the whole app; it writes progress into the query cache.
  useJobProgressSocket(queryClient);
  useApplyAppearance();

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Page><Projects /></Page>} />
        <Route path="/projects/:projectId" element={<Page><ProjectDetail /></Page>} />
        <Route path="/jobs/:jobId" element={<Page><JobDetail /></Page>} />
        <Route path="/jobs/:jobId/events/:eventId" element={<EventReview />} />
        <Route path="/settings" element={<Page><Settings /></Page>} />
      </Routes>
    </AppShell>
  );
}
