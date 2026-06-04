import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Dev proxy target: a running `kyoko serve` (default loopback :8765).
// Override with KYOKO_SERVE_URL when serving on another port.
const KYOKO_SERVE = process.env.KYOKO_SERVE_URL ?? "http://127.0.0.1:8765";

// The built bundle is emitted straight into the Python package so `kyoko serve`
// can ship and serve it as static files. See web.py static-file serving.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: path.resolve(__dirname, "../kyoko/assets/web"),
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    proxy: {
      "/api": { target: KYOKO_SERVE, changeOrigin: true },
      "/v1": { target: KYOKO_SERVE, changeOrigin: true },
    },
  },
});
