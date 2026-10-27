import { useQueryClient } from "@tanstack/react-query";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useJobProgressSocket } from "./lib/queries";
import { Projects } from "./pages/Projects";
import { ProjectDetail } from "./pages/ProjectDetail";
import { JobDetail } from "./pages/JobDetail";
import { EventReview } from "./pages/EventReview";
import { Settings } from "./pages/Settings";
import { cx } from "./components/ui";

export default function App() {
  const queryClient = useQueryClient();
  // One socket for the whole app; it writes progress into the query cache.
  useJobProgressSocket(queryClient);
  // "/" matches every page, so Projects stays lit through a project's runs
  // and reviews, but not on Settings.
  const onSettings = useLocation().pathname.startsWith("/settings");

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-rule bg-abyss/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center gap-6 px-6 py-3">
          <NavLink to="/" className="group flex items-baseline gap-2.5">
            {/* The mark: a sonar return. Cheap, and it makes the window
                identifiable in a dock full of terminals. */}
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full rounded-full bg-signal/40 group-hover:animate-ping" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-signal" />
            </span>
            <span className="text-[15px] font-semibold tracking-[0.2em] uppercase">
              Reef<span className="text-signal">Scanner</span>
            </span>
          </NavLink>

          <nav className="flex items-center gap-1">
            {[
              { to: "/", label: "Projects" },
              { to: "/settings", label: "Settings" },
            ].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cx(
                    "legend rounded-[3px] px-2.5 py-1 transition-colors",
                    isActive && !(item.to === "/" && onSettings)
                      ? "bg-panel-hi text-signal"
                      : "hover:text-read",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <span className="legend ml-auto hidden sm:block">local · offline</span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1500px] flex-1 px-6 py-7">
        <Routes>
          <Route path="/" element={<Projects />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
          <Route path="/jobs/:jobId" element={<JobDetail />} />
          <Route path="/jobs/:jobId/events/:eventId" element={<EventReview />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
