/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

/* Django always serves the HTML (core/templates/core/spa.html), so cookies,
   CSRF, auth and every not-yet-ported page behave exactly as in production.
   In development that page loads its modules from this server instead of the
   built manifest (VITE_DEV_SERVER in Django's .env), which gives HMR. */
const DEV_ORIGIN = "http://localhost:5173";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/static/app/" : "/",
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "../core/static/app",
    emptyOutDir: true,
    /* At the outDir root: collectstatic ignores dot-directories, so Vite's
       default .vite/manifest.json would never reach STATIC_ROOT. */
    manifest: "manifest.json",
    sourcemap: true,
    rollupOptions: { input: "src/main.tsx" },
  },
  server: {
    port: 5173,
    strictPort: true,
    origin: DEV_ORIGIN,
    cors: { origin: [/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/] },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "tests/**/*.test.{ts,tsx}"],
    css: false,
  },
}));
