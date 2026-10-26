import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build lands inside the Python package and is committed: `run.bat` serves
// it without Node. Node is only needed to change the front end.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/static/spa/",
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: "../src/pms/web/static/spa",
    emptyOutDir: true,
    // The phone is the slow client: no source maps to download, and a
    // budget warning that fires before the bundle gets out of hand.
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        // Libraries change far less often than the app: in their own files,
        // a new build of the app re-downloads only the app's chunk.
        codeSplitting: {
          groups: [
            { name: "react", test: /node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/, priority: 3 },
            { name: "motion", test: /node_modules[\\/](motion|motion-dom|motion-utils|framer-motion)[\\/]/, priority: 2 },
            { name: "vendor", test: /node_modules[\\/]/, priority: 1 },
          ],
        },
      },
    },
  },
});
