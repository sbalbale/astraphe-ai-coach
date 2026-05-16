import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    allowedHosts: ["ca52-192-31-112-135.ngrok-free.app"]
  },
  // Pre-bundle Iconify so lazy route chunks don’t hit flaky "Outdated Optimize Dep" (504) after dep / lockfile changes.
  optimizeDeps: {
    include: ["@iconify/svelte", "maplibre-gl"],
  },
  ssr: {
    noExternal: ["@iconify/svelte"]
  }
});
