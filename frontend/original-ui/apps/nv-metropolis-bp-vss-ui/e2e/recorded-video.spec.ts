// SPDX-License-Identifier: MIT

import type { APIRequestContext, Page } from "@playwright/test";
import path from "node:path";

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

  function vstResourceUrl(value: string, runtimeBaseUrl: string): string {
    const url = new URL(value, runtimeBaseUrl);
    const vstPathIndex = url.pathname.indexOf("/vst/");
    expect(vstPathIndex).toBeGreaterThanOrEqual(0);
    return `${url.pathname.slice(vstPathIndex)}${url.search}${url.hash}`;
  }

  async function verifySearchResultMedia(
    page: Page,
    request: APIRequestContext,
    runtimeBaseUrl: string,
    fixturePath: string
  ): Promise<void> {
    const filename = path.basename(fixturePath);
    const playButton = page.getByRole("button", {
      name: `Play ${filename}`,
      exact: true,
    });
    const result = page
      .getByTestId("search-result-card")
      .filter({ has: playButton });
    await expect(result).toHaveCount(1);
    await expect(result).toBeVisible({ timeout: 120_000 });

    const thumbnail = result.getByRole("img", {
      name: filename,
      exact: true,
    });
    await expect(thumbnail).toBeVisible();
    await expect
      .poll(() =>
        thumbnail.evaluate((image) => (image as HTMLImageElement).naturalWidth)
      )
      .toBeGreaterThan(0);

    const thumbnailSrc = await thumbnail.getAttribute("src");
    expect(thumbnailSrc).toBeTruthy();
    const thumbnailPath = new URL(thumbnailSrc!, runtimeBaseUrl).pathname;
    const thumbnailIdentity =
      /^\/api\/v1\/videos\/([^/]+)\/segments\/([^/]+)\/thumbnail$/.exec(
        thumbnailPath
      );
    expect(thumbnailIdentity).not.toBeNull();
    const assetId = decodeURIComponent(thumbnailIdentity![1]);
    expect(assetId).not.toBe("");

    const videoResolverPath = `/api/v1/vst/v1/storage/file/${encodeURIComponent(
      assetId
    )}/url`;
    const videoUrlResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === videoResolverPath
    );
    await playButton.click();

    const videoUrlResponse = await videoUrlResponsePromise;
    expect(videoUrlResponse.status()).toBe(200);
    const videoUrlPayload = (await videoUrlResponse.json()) as {
      videoUrl?: unknown;
    };
    expect(typeof videoUrlPayload.videoUrl).toBe("string");
    expect(videoUrlPayload.videoUrl).not.toBe("");

    const videoModal = page.getByTestId("video-modal");
    await expect(videoModal.getByTestId("video-modal-title")).toHaveText(
      filename
    );
    const videoSource = videoModal.locator("video source");
    await expect(videoSource).toHaveAttribute("src", /\/api\/v1\/vst\//, {
      timeout: 60_000,
    });
    const vstUrl = await videoSource.getAttribute("src");
    expect(vstUrl).toBeTruthy();
    expect(vstResourceUrl(vstUrl!, runtimeBaseUrl)).toBe(
      vstResourceUrl(videoUrlPayload.videoUrl as string, runtimeBaseUrl)
    );

    const range = await request.get(
      new URL(vstUrl!, runtimeBaseUrl).toString(),
      {
        headers: { Range: "bytes=0-9" },
      }
    );
    expect(range.status()).toBe(206);
    const contentRange = range.headers()["content-range"];
    const contentRangeMatch = /^bytes 0-9\/(\d+)$/.exec(contentRange ?? "");
    expect(contentRangeMatch).not.toBeNull();
    expect(Number(contentRangeMatch![1])).toBeGreaterThanOrEqual(10);
    expect((await range.body()).byteLength).toBe(10);

    await videoModal.getByRole("button", { name: "Close video" }).click();
    await expect(videoModal).toBeHidden();
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

    for (const fixturePath of [media.mp4, media.mkv]) {
      await verifySearchResultMedia(page, request, runtimeBaseUrl, fixturePath);
    }
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
    const acceptedResponse = await accepted;
    const completePayload = (await acceptedResponse.json()) as {
      job_id?: unknown;
      status_url?: unknown;
    };
    expect(typeof completePayload.job_id).toBe("string");
    const jobId = completePayload.job_id as string;
    expect(jobId.trim()).not.toBe("");
    const jobPath = `/api/v1/jobs/${encodeURIComponent(jobId)}`;
    expect(completePayload.status_url).toBe(jobPath);

    // This exact progress-dialog state is committed together with jobId.
    await expect(page.getByText("Processing", { exact: true })).toBeVisible();

    const cancelled = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `${jobPath}/cancel`
    );
    await page.getByRole("button", { name: "Cancel All" }).click();
    const cancelledResponse = await cancelled;
    expect(cancelledResponse.request().method()).toBe("POST");
    expect(new URL(cancelledResponse.request().url()).pathname).toBe(
      `${jobPath}/cancel`
    );
    expect(cancelledResponse.status()).toBe(200);
    const cancelPayload = (await cancelledResponse.json()) as {
      job_id?: unknown;
      status?: unknown;
    };
    expect(cancelPayload.job_id).toBe(jobId);
    expect(["running", "cancelled"]).toContain(cancelPayload.status);
    await expect(page.getByText("Cancelled")).toBeVisible();
    await expect(page.getByText("1 cancelled")).toBeVisible();
  });
}
