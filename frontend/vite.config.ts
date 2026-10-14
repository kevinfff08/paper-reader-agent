import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const host = process.env.PAPERREADER_DESKTOP_HOST ?? env.PAPERREADER_DESKTOP_HOST ?? "127.0.0.1";
  const port = process.env.PAPERREADER_DESKTOP_PORT ?? env.PAPERREADER_DESKTOP_PORT ?? "8000";
  const target = `http://${host}:${port}`;
  return {
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/sessions": { target },
      "/healthz": { target },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./vitest.setup.ts",
    globals: true
  }
  };
});
