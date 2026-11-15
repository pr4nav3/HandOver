import { defineConfig } from "vite";

// The UI is plain TypeScript and CSS. It only runs inside the app: every request goes to the
// Rust core through the `call` command, and lesson media comes over the app's `hub` scheme.
export default defineConfig({
  clearScreen: false,
  server: {
    port: 5175,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:5176",
      "/events": "http://127.0.0.1:5176",
      "/hub": "http://127.0.0.1:5176",
    },
  },
  build: {
    target: "es2022",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
