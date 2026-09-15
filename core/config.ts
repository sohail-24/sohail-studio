import fs from "fs";
import path from "path";

export interface StudioSettings {
  ollama_base_url: string;
  chat_model: string;
  devops_model: string;
  terminal_cwd: string;
  shell: string;
  local_only: boolean;
}

export function loadSettings(root: string = process.cwd()): StudioSettings {
  const defaults: StudioSettings = {
    ollama_base_url: "http://localhost:11434",
    chat_model: "devops-qwen:v1",
    devops_model: "devops-qwen:latest",
    terminal_cwd: ".",
    shell: "/bin/bash",
    local_only: true,
  };
  try {
    const settingsPath = path.join(root, "settings", "default.json");
    if (fs.existsSync(settingsPath)) {
      const parsed = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
      return { ...defaults, ...parsed };
    }
  } catch {
    // fallback
  }
  return defaults;
}

const defaultSettings = loadSettings();

export const OLLAMA_BASE_URL = (process.env.OLLAMA_BASE_URL || defaultSettings.ollama_base_url || "http://localhost:11434").replace(/\/+$/, "");
export const OLLAMA_CHAT_MODEL = process.env.OLLAMA_CHAT_MODEL || defaultSettings.chat_model || "devops-qwen:v1";
export const OLLAMA_DEVOPS_MODEL = process.env.OLLAMA_DEVOPS_MODEL || defaultSettings.devops_model || "devops-qwen:latest";
