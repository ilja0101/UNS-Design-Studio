import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The SPA is served by Quart under /spa/ (assets) with an /app fallback route.
// Dev server proxies the API to the running Python app on :5000.
export default defineConfig({
  base: "/spa/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../static/spa",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:5000",
    },
  },
});
