import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The production bundle is written into the Python package so that
// `pip install` + `qpv serve` works without Node.js.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../src/qpvsim/server/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
