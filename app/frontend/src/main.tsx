// Styles before any component: Tailwind declares the cascade layers
// (theme, base, components, utilities), and a component's CSS module loaded
// earlier would declare `components` first and sink below the reset.
import "./index.css";
import "./styles/tokens.css";
import "./styles/base.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { applyAppearance, DEFAULT_APPEARANCE } from "./lib/appearance";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Everything here is local: refetching on focus buys nothing and makes
      // the desktop window flicker whenever it regains focus.
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5_000,
    },
  },
});

// Follow macOS until the saved appearance arrives, so the first paint is
// already in the right mode.
applyAppearance(DEFAULT_APPEARANCE);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
