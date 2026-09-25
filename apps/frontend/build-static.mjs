// Builds the GUI into apps/backend/copilot/static (app.js + app.css), the bundle the copilot backend serves
// at http://localhost:8080 so the app runs without Node.js. Run: npm run build:static
import { build } from "esbuild";

await build({
  entryPoints: ["src/main.tsx"],
  outfile: "../backend/copilot/static/app.js",
  bundle: true,
  minify: true,
  format: "iife",
  jsx: "automatic",
  target: "es2020",
  define: {
    "process.env.NODE_ENV": '"production"',
    // Same-origin API: the backend serves both the GUI and /api.
    "import.meta.env.VITE_API_BASE_URL": '""',
  },
  logLevel: "info",
});
