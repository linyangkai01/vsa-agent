// SPDX-License-Identifier: MIT
import type { Page } from "@playwright/test";

if (process.env.JEST_WORKER_ID) {
  describe.skip("recorded-video Playwright acceptance", () => {
    it("runs only through the Playwright runner", () => undefined);
  });
} else {
  const { createRecordedVideoFixtures, expect, test } =
    require("./fixtures") as typeof import("./fixtures");

  test.describe.configure({ mode: "serial" });

  async function openVideoManagement(page: Page): Promise<void> {
    await page.getByTestId("sidebar-tab-video-management").click();
    await expect(
      page.getByRole("button", { name: "+ Upload Video" })
    ).toBeVisible();
  }

  async function chooseRecordedVideos(
    page: Page,
    files: string[]
  ): Promise<void> {
    await openVideoManagement(page);
    await page
      .locator('input[type="file"][accept=".mp4,.mkv"]')
      .last()
      .setInputFiles(files);
    await expect(page.getByText("Upload Files", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: `Upload (${files.length})` })
      .click();
  }

  test("uploads, indexes and plays MP4 and MKV recorded-video segments", async ({
    page,
    request,
    runtimeBaseUrl,
  }, testInfo) => {
    const media = await createRecordedVideoFixtures(testInfo.outputDir);

    await page.goto(runtimeBaseUrl);
    await chooseRecordedVideos(page, [media.mp4, media.mkv]);

    await expect(page.getByText("Processing...").first()).toBeVisible({
      timeout: 120_000,
    });
    await expect(page.getByText("Completed")).toHaveCount(2, {
      timeout: 600_000,
    });

    await page.getByTestId("sidebar-tab-search").click();
    const searchInput = page.getByPlaceholder("Search Files");
    await expect(searchInput).toBeEnabled();
    await searchInput.fill("forklift");
    await page.getByRole("button", { name: "Search", exact: true }).click();

    const result = page.getByTestId("search-result-card").first();
    await expect(result).toBeVisible({ timeout: 120_000 });
    const thumbnail = result.locator("img");
    await expect(thumbnail).toBeVisible();
    await expect
      .poll(() =>
        thumbnail.evaluate((image) => (image as HTMLImageElement).naturalWidth)
      )
      .toBeGreaterThan(0);
    expect(await thumbnail.getAttribute("src")).toContain("/api/v1/videos/");

    await result.getByTestId("video-play-overlay").click();
    const videoSource = page.getByTestId("video-modal").locator("video source");
    await expect(videoSource).toHaveAttribute("src", /\/api\/v1\/vst\//, {
      timeout: 60_000,
    });
    const vstUrl = await videoSource.getAttribute("src");
    expect(vstUrl).toBeTruthy();

    const range = await request.get(
      new URL(vstUrl!, runtimeBaseUrl).toString(),
      {
        headers: { Range: "bytes=0-9" },
      }
    );
    expect(range.status()).toBe(206);
    expect(range.headers()["content-range"]).toMatch(/^bytes 0-9\//);
    expect((await range.body()).byteLength).toBe(10);
  });

  test("shows a real failed job and retries the same recorded-video job", async ({
    page,
    runtimeBaseUrl,
  }, testInfo) => {
    const media = await createRecordedVideoFixtures(testInfo.outputDir);

    await page.goto(runtimeBaseUrl);
    await chooseRecordedVideos(page, [media.corruptMkv]);

    await expect(
      page.getByText("Recorded video processing failed")
    ).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText("1 failed")).toBeVisible();

    await page
      .getByRole("button", { name: `Retry ${media.corruptMkvName}` })
      .click();
    await expect(page.getByText("Processing...")).toBeVisible();
    await expect(
      page.getByText("Recorded video processing failed")
    ).toBeVisible({ timeout: 180_000 });
  });

  test("cancels a real processing job from the upload progress dialog", async ({
    page,
    runtimeBaseUrl,
  }, testInfo) => {
    const media = await createRecordedVideoFixtures(testInfo.outputDir);

    await page.goto(runtimeBaseUrl);
    const accepted = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/api\/v1\/videos\/[^/]+\/complete$/.test(
          new URL(response.url()).pathname
        ) &&
        response.status() === 202
    );
    await chooseRecordedVideos(page, [media.cancelMkv]);
    await accepted;
    await expect(page.getByText("Processing...")).toBeVisible();

    const cancelled = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/api\/v1\/jobs\/[^/]+\/cancel$/.test(new URL(response.url()).pathname)
    );
    await page.getByRole("button", { name: "Cancel All" }).click();
    expect((await cancelled).status()).toBe(200);
    await expect(page.getByText("Cancelled")).toBeVisible();
    await expect(page.getByText("1 cancelled")).toBeVisible();
  });
}
