import { defineConfig, Plugin } from "vite";
import react from "@vitejs/plugin-react";
import * as path from "node:path";
import * as fs from "node:fs";

function syncToLifecyclePlugin(): Plugin {
  return {
    name: "sync-to-lifecycle",
    closeBundle() {
      const srcDir = path.resolve(__dirname, "../views/audit");
      const destDir = path.resolve(__dirname, "../views/lifecycle");
      if (fs.existsSync(srcDir)) {
        if (!fs.existsSync(destDir)) {
          fs.mkdirSync(destDir, { recursive: true });
        }
        fs.cpSync(srcDir, destDir, { recursive: true });
        console.log(`[sync-to-lifecycle] Successfully synchronized ${srcDir} to ${destDir}`);
      }
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), syncToLifecyclePlugin()],
  base: "./",
  build: {
    outDir: "../views/audit",
    emptyOutDir: true,
  },
});
