import { defineConfig } from "vite";

// The UI is plain TypeScript and CSS. It only runs inside the app: every request goes to the
// Rust core through the `call` command, and lesson media comes over the app's `hub` scheme.
export default defineConfig({
  clearScreen: false,
  server: {
    port: 5175,
    strictPort: true,
  },
  build: {
    target: "es2022",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
