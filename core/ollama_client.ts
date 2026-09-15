import { ReadOnlyControlPlane } from "./control_plane.js";

export interface OllamaChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_calls?: Array<{
    id?: string;
    type?: string;
    function: {
      name: string;
      arguments: Record<string, any> | string;
    };
  }>;
}

export interface OllamaChatOptions {
  baseUrl?: string;
  model?: string;
  messages: OllamaChatMessage[];
  controlPlane: ReadOnlyControlPlane;
  onChunk?: (chunk: string) => void;
}

export class OllamaUnavailableError extends Error {
  public baseUrl: string;
  public model: string;

  constructor(baseUrl: string, model: string, details?: string) {
    const msg = `Ollama is unavailable at ${baseUrl} (model: ${model}). Please ensure the local Ollama daemon is running.${details ? ` (${details})` : ""}`;
    super(msg);
    this.name = "OllamaUnavailableError";
    this.baseUrl = baseUrl;
    this.model = model;
  }
}

export class OllamaClient {
  private baseUrl: string;
  private chatModel: string;

  constructor(baseUrl?: string, chatModel?: string) {
    this.baseUrl = (baseUrl || process.env.OLLAMA_BASE_URL || "http://localhost:11434").replace(/\/+$/, "");
    this.chatModel = chatModel || process.env.OLLAMA_CHAT_MODEL || "devops-qwen:v1";
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  public getChatModel(): string {
    return this.chatModel;
  }

  /**
   * Health check to ping Ollama daemon.
   */
  public async checkHealth(timeoutMs: number = 2000): Promise<{ ok: boolean; error?: string }> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(`${this.baseUrl}/api/version`, {
        method: "GET",
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        return { ok: false, error: `HTTP ${response.status}: ${response.statusText}` };
      }
      return { ok: true };
    } catch (err: any) {
      clearTimeout(timeoutId);
      return { ok: false, error: err.message || "Connection refused" };
    }
  }

  /**
   * Stream a chat completion from Ollama HTTP API with Read-Only Control Plane evidence.
   */
  public async streamChat(options: OllamaChatOptions): Promise<string> {
    const baseUrl = (options.baseUrl || this.baseUrl).replace(/\/+$/, "");
    const model = options.model || this.chatModel;
    const { messages, controlPlane, onChunk } = options;

    const tools = controlPlane.getOllamaToolDefinitions();

    let currentMessages = [...messages];
    let maxToolLoops = 5;

    while (maxToolLoops > 0) {
      maxToolLoops--;

      let response: Response;
      try {
        response = await fetch(`${baseUrl}/api/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model,
            messages: currentMessages,
            stream: true,
            tools,
          }),
        });
      } catch (err: any) {
        throw new OllamaUnavailableError(baseUrl, model, err.message);
      }

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        throw new OllamaUnavailableError(baseUrl, model, `HTTP ${response.status} - ${errorText}`);
      }

      if (!response.body) {
        throw new OllamaUnavailableError(baseUrl, model, "Empty response body from Ollama stream.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let fullContent = "";
      let pendingToolCalls: any[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          let parsed: any;
          try {
            parsed = JSON.parse(trimmed);
          } catch {
            continue;
          }

          if (parsed.error) {
            throw new OllamaUnavailableError(baseUrl, model, parsed.error);
          }

          if (parsed.message) {
            // Check for tool calls
            if (parsed.message.tool_calls && parsed.message.tool_calls.length > 0) {
              pendingToolCalls.push(...parsed.message.tool_calls);
            }

            // Stream text chunk
            if (parsed.message.content) {
              const chunk = parsed.message.content;
              fullContent += chunk;
              if (onChunk) {
                onChunk(chunk);
              }
            }
          }
        }
      }

      // Check remaining buffer
      if (buffer.trim()) {
        try {
          const parsed = JSON.parse(buffer.trim());
          if (parsed.message?.content) {
            fullContent += parsed.message.content;
            if (onChunk) onChunk(parsed.message.content);
          }
          if (parsed.message?.tool_calls) {
            pendingToolCalls.push(...parsed.message.tool_calls);
          }
        } catch {
          // ignore
        }
      }

      // If Ollama invoked tools, execute them on Read-Only Control Plane and loop back
      if (pendingToolCalls.length > 0) {
        currentMessages.push({
          role: "assistant",
          content: fullContent,
          tool_calls: pendingToolCalls,
        });

        for (const call of pendingToolCalls) {
          const fnName = call.function?.name;
          let fnArgs: any = {};
          if (typeof call.function?.arguments === "string") {
            try {
              fnArgs = JSON.parse(call.function.arguments);
            } catch {
              fnArgs = {};
            }
          } else if (call.function?.arguments) {
            fnArgs = call.function.arguments;
          }

          // Strict Read-Only execution
          const evidence = await controlPlane.executeReadOnlyTool(fnName, fnArgs);

          currentMessages.push({
            role: "tool",
            content: JSON.stringify(evidence),
          });
        }

        // Reset for the next streaming round with tool results
        pendingToolCalls = [];
        fullContent = "";
        continue;
      }

      return fullContent;
    }

    return "";
  }
}
