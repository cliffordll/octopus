import { describe, expect, it } from "vitest";
import { runtimeModelLabel, runtimeModelReference } from "../utils/runtimeModels";

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
});
