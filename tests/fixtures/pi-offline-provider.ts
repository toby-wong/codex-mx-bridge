// Test-only provider: produces deterministic events locally; makes no requests.
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";

const pause = (ms) => new Promise(resolve => setTimeout(resolve, ms));

export default function (pi) {
  pi.registerProvider("mx-fixture", {
    api: "mx-fixture-api", apiKey: "offline-fixture", baseUrl: "http://127.0.0.1:1",
    models: [{ id: "fixture", name: "MX offline fixture", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 1000 }],
    streamSimple(model, context) {
      const stream = createAssistantMessageEventStream();
      void (async () => {
        const message = {
          role: "assistant", content: [], api: model.api, provider: model.provider, model: model.id,
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
          stopReason: "pending", timestamp: Date.now(),
        };
        stream.push({ type: "start", partial: message });
        await pause(300);
        if (process.env.MX_PI_SMOKE_FAILURE === "1") {
          message.stopReason = "error";
          message.errorMessage = "Deliberate offline fixture failure";
          stream.push({ type: "error", reason: "error", error: message });
        } else if (!context.messages.some(item => item.role === "toolResult")) {
          const delegate = process.env.MX_PI_SMOKE_DELEGATE === "1" && !process.env.PI_SUBAGENT_ID;
          const toolCall = { type: "toolCall", id: "mx_fixture_call",
            name: delegate ? "subagent" : "mx_fixture_tool",
            arguments: delegate ? { name: "mx-pi-probe-test-1", task: "Return the offline test marker.",
              model: "mx-fixture/fixture", thinking: "off", persistent: true, agent: "fast" } : {} };
          message.content.push(toolCall);
          stream.push({ type: "toolcall_start", contentIndex: 0, partial: message });
          stream.push({ type: "toolcall_end", contentIndex: 0, toolCall, partial: message });
          message.stopReason = "toolUse";
          stream.push({ type: "done", reason: "toolUse", message });
        } else {
          message.content.push({ type: "text", text: "" });
          stream.push({ type: "text_start", contentIndex: 0, partial: message });
          message.content[0].text = "MX_PI_OFFLINE_OK";
          stream.push({ type: "text_delta", contentIndex: 0, delta: "MX_PI_OFFLINE_OK", partial: message });
          stream.push({ type: "text_end", contentIndex: 0, content: "MX_PI_OFFLINE_OK", partial: message });
          message.stopReason = "stop";
          stream.push({ type: "done", reason: "stop", message });
        }
        stream.end();
      })();
      return stream;
    },
  });
  pi.registerTool({
    name: "mx_fixture_tool", label: "MX fixture", description: "Local bridge lifecycle fixture",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute() {
      await pause(300);
      return { content: [{ type: "text", text: "Fixture tool complete" }], details: {} };
    },
  });
  // Leave enough time to observe the status through the real Python writer.
  pi.on("agent_settled", async () => { await pause(300); });
}
