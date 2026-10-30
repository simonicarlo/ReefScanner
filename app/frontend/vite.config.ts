import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// The build lands inside the Python package so `pip install reefscanner-app`
// ships the UI and the desktop shell has something to open offline.
const PACKAGE_STATIC = path.resolve(__dirname, "../src/reefscanner/app/static");

// Where `npm run dev` sends API traffic. The backend is `reefscanner serve`.
const BACKEND = process.env.REEFSCANNER_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: PACKAGE_STATIC,
    emptyOutDir: true,
  },
  server: {
    // Proxying (rather than a CORS origin) keeps the frontend same-origin in
    // dev too, so nothing behaves differently once it's bundled.
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
});
