import { afterEach, describe, expect, it } from "vitest";
import { runErrorMessage } from "../utils/display";
import { LOCALE_STORAGE_KEY } from "../utils/locale";

afterEach(() => {
  localStorage.clear();
});

describe("runErrorMessage", () => {
  it("uses Chinese friendly copy for interrupted child processes", () => {
    expect(runErrorMessage("Process lost -- child pid 31740 is no longer running")).toBe("运行进程已中断。子进程在服务完成跟踪前已退出。");
    expect(runErrorMessage("^C")).toBe("运行被 Ctrl+C 中断。");
  });

  it("uses English friendly copy when English locale is selected", () => {
    localStorage.setItem(LOCALE_STORAGE_KEY, "en-US");
    expect(runErrorMessage("Process lost -- child pid 31740 is no longer running")).toBe(
      "Run process was interrupted. The child process exited before the server finished tracking it.",
    );
    expect(runErrorMessage("^C")).toBe("Run was interrupted by Ctrl+C.");
  });

  it("keeps unknown runtime errors intact", () => {
    expect(runErrorMessage("Separator is found in model output")).toBe("Separator is found in model output");
  });
});
