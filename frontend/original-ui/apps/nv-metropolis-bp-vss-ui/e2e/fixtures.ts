// SPDX-License-Identifier: MIT

import { expect, test as base } from "@playwright/test";
import { spawn } from "node:child_process";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

export interface RecordedVideoFixtures {
  mp4: string;
  mkv: string;
  cancelMkv: string;
  corruptMkv: string;
  corruptMkvName: string;
}

type RuntimeFixtures = {
  providerControlUrl: string;
  runtimeBaseUrl: string;
};

function normalizedRuntimeUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch (error) {
    throw new Error(`Recorded-video E2E runtime URL is invalid: ${value}`, {
      cause: error,
    });
  }
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error(
      `Recorded-video E2E runtime URL must use HTTP(S): ${value}`
    );
  }
  return url.toString().replace(/\/$/, "");
}

async function runFfmpeg(
  outputPath: string,
  codecArgs: string[],
  durationSeconds = 4
): Promise<void> {
  const args = [
    "-hide_banner",
    "-loglevel",
    "error",
    "-y",
    "-f",
    "lavfi",
    "-i",
    `testsrc2=duration=${durationSeconds}:size=320x180:rate=8`,
    "-an",
    ...codecArgs,
    outputPath,
  ];

  await new Promise<void>((resolve, reject) => {
    const child = spawn("ffmpeg", args, { windowsHide: true });
    let stderr = "";
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.once("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        reject(
          new Error(
            "ffmpeg is required for recorded-video E2E fixtures but was not found on PATH. " +
              "Install ffmpeg and verify `ffmpeg -version` succeeds before rerunning Playwright.",
            { cause: error }
          )
        );
        return;
      }
      reject(
        new Error(`Unable to start ffmpeg for ${path.basename(outputPath)}`, {
          cause: error,
        })
      );
    });
    child.once("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(
        new Error(
          `ffmpeg failed to create ${path.basename(
            outputPath
          )} (exit ${code}). ${stderr.trim()}`
        )
      );
    });
  });
}

export async function createRecordedVideoFixtures(
  outputDir: string
): Promise<RecordedVideoFixtures> {
  await mkdir(outputDir, { recursive: true });
  const mp4 = path.join(outputDir, "forklift-playwright.mp4");
  const mkv = path.join(outputDir, "forklift-playwright.mkv");
  const cancelMkv = path.join(outputDir, "cancel-playwright.mkv");
  const corruptMkv = path.join(outputDir, "corrupt-playwright.mkv");

  await runFfmpeg(mp4, ["-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p"]);
  await runFfmpeg(mkv, ["-c:v", "ffv1"]);
  await copyFile(mkv, cancelMkv);

  const validMkv = await readFile(mkv);
  const corruptPrefix = new Uint8Array(Math.min(64, validMkv.byteLength));
  corruptPrefix.set(validMkv.subarray(0, corruptPrefix.byteLength));
  await writeFile(corruptMkv, corruptPrefix);

  return {
    mp4,
    mkv,
    cancelMkv,
    corruptMkv,
    corruptMkvName: path.basename(corruptMkv),
  };
}

export const test = base.extend<RuntimeFixtures>({
  providerControlUrl: async ({ request }, provideProviderControlUrl) => {
    const candidate =
      process.env.PLAYWRIGHT_PROVIDER_BASE_URL ||
      (process.env.RUNTIME_BASE_URL ? undefined : "http://127.0.0.1:8399");
    if (!candidate) {
      throw new Error(
        "Deterministic cancellation requires PLAYWRIGHT_PROVIDER_BASE_URL when RUNTIME_BASE_URL is set."
      );
    }
    const providerControlUrl = normalizedRuntimeUrl(candidate);
    const health = await request.get(`${providerControlUrl}/health`);
    if (!health.ok()) {
      throw new Error(
        `Recorded-video E2E provider returned HTTP ${health.status()} at ${providerControlUrl}`
      );
    }
    await provideProviderControlUrl(providerControlUrl);
  },
  runtimeBaseUrl: async ({ baseURL, request }, provideRuntimeBaseUrl) => {
    const candidate = process.env.RUNTIME_BASE_URL || baseURL;
    if (!candidate) {
      throw new Error(
        "Recorded-video E2E runtime is not configured. Set RUNTIME_BASE_URL or use the Playwright " +
          "webServer backed by scripts/es-runtime-stack.sh --validate --keep-running."
      );
    }
    const runtimeBaseUrl = normalizedRuntimeUrl(candidate);

    let home;
    try {
      home = await request.get(runtimeBaseUrl);
    } catch (error) {
      throw new Error(
        `Recorded-video E2E runtime is unreachable at ${runtimeBaseUrl}`,
        { cause: error }
      );
    }
    if (!home.ok()) {
      throw new Error(
        `Recorded-video E2E UI returned HTTP ${home.status()} at ${runtimeBaseUrl}`
      );
    }

    const proxy = await request.get(`${runtimeBaseUrl}/api/v1/search`);
    if (proxy.status() !== 405) {
      throw new Error(
        `Recorded-video same-origin proxy readiness failed at ${runtimeBaseUrl}/api/v1/search: ` +
          `expected HTTP 405, received ${proxy.status()}`
      );
    }

    await provideRuntimeBaseUrl(runtimeBaseUrl);
  },
});

export { expect };
