import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The SPA is served by Quart under /spa/ (assets) with an /app fallback route.
// Dev server proxies the API to the running Python app on :5000.
//
// base:"./" makes the built asset URLs relative so they resolve against the
// document's <base> tag. index.html carries <base href="/spa/"> (where the
// assets are served) for standalone; in AMIX governed mode the app rewrites that
// <base> to "{prefix}spa/" so the portal-proxied app resolves the same assets.
export default defineConfig({
  base: "./",
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
