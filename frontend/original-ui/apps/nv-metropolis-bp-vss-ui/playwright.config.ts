// SPDX-License-Identifier: MIT

import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const repoRoot = path.resolve(__dirname, "../../../..");
const uiPort = Number(process.env.PLAYWRIGHT_UI_PORT || 3300);
const apiPort = Number(process.env.PLAYWRIGHT_API_PORT || 8300);
const runtimeBaseUrl = (
  process.env.RUNTIME_BASE_URL || `http://127.0.0.1:${uiPort}`
).replace(/\/$/, "");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 600_000,
  expect: {
    timeout: 30_000,
  },
  outputDir: "test-results",
  reporter: [["list"]],
  use: {
    baseURL: runtimeBaseUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.RUNTIME_BASE_URL
    ? undefined
    : {
        command: [
          "bash scripts/es-runtime-stack.sh",
          "--validate",
          "--keep-running",
          `--api-port ${apiPort}`,
          `--ui-port ${uiPort}`,
          "--timeout-sec 180",
          "--stop-elasticsearch",
        ].join(" "),
        cwd: repoRoot,
        url: runtimeBaseUrl,
        reuseExistingServer: false,
        timeout: 300_000,
        stdout: "pipe",
        stderr: "pipe",
      },
});
