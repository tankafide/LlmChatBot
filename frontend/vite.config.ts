import { defineConfig } from "vite";
// Backend turns are bounded to 60 seconds; allow commit and proxy overhead.
export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
        proxyTimeout: 120_000,
        timeout: 125_000,
      },
    },
  },
});
