import { describe, expect, it } from "vitest";
import { applyRuntimeModelConfig, MODEL_PROVIDER_RUNTIMES, runtimeConfigAfterSwitch, runtimeModelLabel, runtimeModelReference, supportsRuntimeModels } from "../utils/runtimeModels";

describe("runtime model references", () => {
  it("uses the server provider id when model id is provider-local", () => {
    const model = {
      providerId: "deepseek",
      modelId: "deepseek-v4-flash",
      displayName: "deepseek-v4-flash (local)",
      runtimeType: "opencode_local" as const,
    };

    expect(runtimeModelReference(model)).toBe("deepseek/deepseek-v4-flash");
    expect(runtimeModelLabel(model)).toBe("deepseek-v4-flash (local) (deepseek/deepseek-v4-flash)");
  });

  it("keeps a full model reference returned by the server", () => {
    const model = {
      providerId: "deepseek",
      modelId: "deepseek/deepseek-v4-flash",
      runtimeType: "opencode_local" as const,
    };

    expect(runtimeModelReference(model)).toBe("deepseek/deepseek-v4-flash");
    expect(runtimeModelLabel(model)).toBe("deepseek/deepseek-v4-flash");
  });

  it("supports provider models only for runtimes with model catalogs", () => {
    expect(MODEL_PROVIDER_RUNTIMES).toEqual([
      "opencode_local",
      "codex_local",
      "claude_local",
      "openclaw_local",
    ]);
    expect(supportsRuntimeModels("codex_local")).toBe(true);
    expect(supportsRuntimeModels("claude_local")).toBe(true);
    expect(supportsRuntimeModels("openclaw_local")).toBe(true);
    expect(supportsRuntimeModels("openclaw_gateway")).toBe(false);
    expect(supportsRuntimeModels("process")).toBe(false);
  });

  it("clears runtime-specific values when switching adapters", () => {
    expect(runtimeConfigAfterSwitch(
      {
        model: "ollama/qwen2.5:1.5b",
        command: "opencode",
        extraArgs: ["--dangerously-skip-permissions"],
        timeoutSec: 60,
        instructionsEntryFile: "SOUL.md",
      },
      "opencode_local",
      "codex_local",
    )).toEqual({ timeoutSec: 60, instructionsEntryFile: "SOUL.md" });
  });

  it("uses the Codex CLI default model and removes OpenCode arguments", () => {
    expect(applyRuntimeModelConfig(
      {
        model: "ollama/qwen2.5:1.5b",
        extraArgs: ["--verbose", "--dangerously-skip-permissions"],
      },
      "codex_local",
      "",
    )).toEqual({ extraArgs: ["--verbose"] });
  });
});
