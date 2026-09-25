import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the copilot backend (COPILOT_BACKEND_URL, default http://localhost:8080).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.COPILOT_BACKEND_URL ?? "http://localhost:8080" },
  },
  test: { environment: "node" },
});
