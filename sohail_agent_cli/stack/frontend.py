"""Frontend stack skeletons."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path


class FrontendSkeletons:
    """Create frontend-only technology skeletons."""

    def generate(self, technology: str | None) -> OrderedDict[Path, str]:
        """Generate frontend files for a normalized technology name."""
        files: OrderedDict[Path, str] = OrderedDict()
        if technology == "react":
            files.update(self._react())
        return files

    @staticmethod
    def _react() -> OrderedDict[Path, str]:
        files: OrderedDict[Path, str] = OrderedDict()
        files[Path("frontend/package.json")] = """{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest",
    "typescript": "latest",
    "react": "latest",
    "react-dom": "latest"
  },
  "devDependencies": {}
}
"""
        files[Path("frontend/vite.config.ts")] = """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
"""
        files[Path("frontend/src/main.tsx")] = """import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
"""
        files[Path("frontend/src/App.tsx")] = """export function App() {
  return (
    <main>
      <h1>React stack skeleton</h1>
    </main>
  );
}
"""
        files[Path("frontend/public/.gitkeep")] = ""
        return files
