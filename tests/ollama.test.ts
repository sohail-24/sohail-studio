import test, { describe, it } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { OllamaClient, OllamaUnavailableError } from "../core/ollama_client.js";
import { ReadOnlyControlPlane } from "../core/control_plane.js";
import { OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, OLLAMA_DEVOPS_MODEL } from "../core/config.js";

describe("Ollama Integration & Architectural Separation", () => {
  const controlPlane = new ReadOnlyControlPlane(process.cwd());

  it("1. Chat Model is devops-qwen:v1 and Sohail-Agent Model is devops-qwen:latest (Separation)", () => {
    const client = new OllamaClient();
    assert.equal(client.getChatModel(), "devops-qwen:v1", "Chat model must default to devops-qwen:v1");
    assert.equal(OLLAMA_CHAT_MODEL, "devops-qwen:v1", "Server Chat model must be devops-qwen:v1");
    assert.equal(OLLAMA_DEVOPS_MODEL, "devops-qwen:latest", "Sohail-Agent model must be devops-qwen:latest");
    assert.notEqual(OLLAMA_CHAT_MODEL, OLLAMA_DEVOPS_MODEL, "Chat and Sohail-Agent must use separate models");
  });

  it("2. Base URL configuration defaults to http://localhost:11434 and accepts overrides", () => {
    const defaultClient = new OllamaClient();
    assert.equal(defaultClient.getBaseUrl(), "http://localhost:11434");
    assert.equal(OLLAMA_BASE_URL, "http://localhost:11434");

    const customClient = new OllamaClient("http://192.168.1.100:11434", "devops-qwen:v1");
    assert.equal(customClient.getBaseUrl(), "http://192.168.1.100:11434");
    assert.equal(customClient.getChatModel(), "devops-qwen:v1");
  });

  it("3. Ollama unavailable / error handling: throws clear operational error without fake mentor fallback", async () => {
    // Non-existent port to simulate daemon being offline
    const offlineClient = new OllamaClient("http://127.0.0.1:59999", "devops-qwen:v1");

    await assert.rejects(
      async () => {
        await offlineClient.streamChat({
          messages: [{ role: "user", content: "Hello" }],
          controlPlane,
        });
      },
      (err: any) => {
        assert.ok(err instanceof OllamaUnavailableError, "Error must be OllamaUnavailableError");
        assert.ok(
          err.message.includes("Ollama is unavailable at http://127.0.0.1:59999 (model: devops-qwen:v1)"),
          "Error message must specify base URL and model clearly"
        );
        return true;
      }
    );
  });

  it("4. Streaming response handling from Ollama HTTP API", async () => {
    // Spin up a transient mock Ollama server
    const server = http.createServer((req, res) => {
      if (req.url === "/api/chat" && req.method === "POST") {
        res.writeHead(200, {
          "Content-Type": "application/x-ndjson",
          "Transfer-Encoding": "chunked",
        });

        const chunk1 = JSON.stringify({
          model: "devops-qwen:v1",
          message: { role: "assistant", content: "Hello " },
          done: false,
        }) + "\n";

        const chunk2 = JSON.stringify({
          model: "devops-qwen:v1",
          message: { role: "assistant", content: "from Ollama!" },
          done: true,
        }) + "\n";

        res.write(chunk1);
        setTimeout(() => {
          res.write(chunk2);
          res.end();
        }, 30);
      } else {
        res.writeHead(404);
        res.end();
      }
    });

    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
    const port = (server.address() as any).port;
    const testUrl = `http://127.0.0.1:${port}`;

    try {
      const client = new OllamaClient(testUrl, "devops-qwen:v1");
      const streamedChunks: string[] = [];

      const fullText = await client.streamChat({
        baseUrl: testUrl,
        model: "devops-qwen:v1",
        messages: [{ role: "user", content: "Hi" }],
        controlPlane,
        onChunk: (c) => streamedChunks.push(c),
      });

      assert.equal(fullText, "Hello from Ollama!");
      assert.deepEqual(streamedChunks, ["Hello ", "from Ollama!"]);
    } finally {
      server.close();
    }
  });

  it("5. Strict safety: Chat cannot execute arbitrary shell commands", async () => {
    const cp = new ReadOnlyControlPlane(process.cwd());

    // Try executing a shell command via Control Plane
    const result = await cp.executeReadOnlyTool("bash", { command: "rm -rf /" });
    assert.equal(result.status, "error");
    assert.ok(result.error?.includes("SecurityException"));
  });
});
