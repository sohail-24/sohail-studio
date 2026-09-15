/**
 * Ollama Output Processing (Node.js/TypeScript)
 * Equivalent to historical core/ollama_output.py
 * Cleans streaming chunks and model output from Ollama devops-qwen:v1.
 */

export function cleanOllamaOutput(text: string): string {
  if (!text) return "";
  let cleaned = text;

  // 1. Remove complete <think>...</think> tags
  cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, "");

  // 2. Remove unclosed <think> tag if at start or end of response
  cleaned = cleaned.replace(/<think>[\s\S]*$/gi, "");

  // 3. Remove prompt leakage if any repeated by model
  cleaned = cleaned.replace(/=== LOCAL CONTROL PLANE FACTS[\s\S]*?=== END FACTS ===/gi, "");

  // 4. Normalize carriage returns
  cleaned = cleaned.replace(/\r\n/g, "\n");

  return cleaned.trim();
}

export function processOllamaStreamChunk(
  chunk: string,
  state: { inThinkingTag: boolean }
): string | null {
  if (!chunk) return null;
  let text = chunk;

  if (state.inThinkingTag) {
    const endTagIndex = text.indexOf("</think>");
    if (endTagIndex !== -1) {
      state.inThinkingTag = false;
      text = text.substring(endTagIndex + 8);
    } else {
      return null;
    }
  }

  const startTagIndex = text.indexOf("<think>");
  if (startTagIndex !== -1) {
    const before = text.substring(0, startTagIndex);
    const endTagIndex = text.indexOf("</think>", startTagIndex);
    if (endTagIndex !== -1) {
      const after = text.substring(endTagIndex + 8);
      return before + after;
    } else {
      state.inThinkingTag = true;
      return before || null;
    }
  }

  return text;
}
