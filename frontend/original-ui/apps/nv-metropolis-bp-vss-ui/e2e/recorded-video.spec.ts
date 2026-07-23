// SPDX-License-Identifier: MIT

import type { APIRequestContext, Page, Response } from "@playwright/test";
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

  type CompletedUploadEvidence = {
    assetId: string;
    filename: string;
    jobId: string;
    status: "queued";
    statusUrl: string;
  };

  function requiredString(value: unknown, field: string): string {
    expect(typeof value, `${field} must be a string`).toBe("string");
    const result = value as string;
    expect(result.trim(), `${field} must not be empty`).not.toBe("");
    return result;
  }

  async function parseCompletedUpload(
    response: Response
  ): Promise<CompletedUploadEvidence> {
    expect(response.request().method()).toBe("POST");
    expect(response.status()).toBe(202);
    const completePath = new URL(response.url()).pathname;
    const completeIdentity = /^\/api\/v1\/videos\/([^/]+)\/complete$/.exec(
      completePath
    );
    expect(completeIdentity).not.toBeNull();

    const requestPayload = response.request().postDataJSON() as {
      filename?: unknown;
    };
    const filename = requiredString(requestPayload.filename, "filename");
    const payload = (await response.json()) as {
      asset_id?: unknown;
      job_id?: unknown;
      status?: unknown;
      status_url?: unknown;
    };
    const assetId = requiredString(payload.asset_id, "asset_id");
    const jobId = requiredString(payload.job_id, "job_id");
    const statusUrl = requiredString(payload.status_url, "status_url");
    expect(payload.status).toBe("queued");
    expect(decodeURIComponent(completeIdentity![1])).toBe(assetId);
    expect(statusUrl).toBe(`/api/v1/jobs/${encodeURIComponent(jobId)}`);

    return { assetId, filename, jobId, status: "queued", statusUrl };
  }

  async function captureCompletedUploads(
    page: Page,
    count: number,
    action: () => Promise<void>
  ): Promise<CompletedUploadEvidence[]> {
    const responses: Response[] = [];
    const capture = (response: Response) => {
      if (
        response.request().method() === "POST" &&
        response.status() === 202 &&
        /^\/api\/v1\/videos\/[^/]+\/complete$/.test(
          new URL(response.url()).pathname
        )
      ) {
        responses.push(response);
      }
    };

    page.on("response", capture);
    try {
      await action();
      await expect
        .poll(() => responses.length, { timeout: 120_000 })
        .toBe(count);
    } finally {
      page.off("response", capture);
    }

    return Promise.all(responses.map(parseCompletedUpload));
  }

  async function verifySearchResultMedia(
    page: Page,
    request: APIRequestContext,
    runtimeBaseUrl: string,
    fixturePath: string
  ): Promise<string> {
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
    const thumbnailResponse = await request.get(
      new URL(thumbnailSrc!, runtimeBaseUrl).toString()
    );
    expect(thumbnailResponse.status()).toBe(200);
    expect(thumbnailResponse.headers()["content-type"]).toMatch(/^image\//);

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
    return assetId;
  }

  test("uploads, indexes and plays MP4 and MKV recorded-video segments", async ({
    page,
    request,
    runtimeBaseUrl,
  }, testInfo) => {
    const media = await createRecordedVideoFixtures(testInfo.outputDir);

    await page.goto(runtimeBaseUrl);
    const completedUploads = await captureCompletedUploads(page, 2, () =>
      chooseRecordedVideos(page, [media.mp4, media.mkv])
    );
    const mp4Upload = completedUploads.find(
      (upload) => upload.filename === path.basename(media.mp4)
    );
    const mkvUpload = completedUploads.find(
      (upload) => upload.filename === path.basename(media.mkv)
    );
    expect(mp4Upload).toBeDefined();
    expect(mkvUpload).toBeDefined();
    if (!mp4Upload || !mkvUpload) {
      throw new Error("MP4 and MKV completion responses must both be captured");
    }
    expect(mp4Upload.assetId).not.toBe(mkvUpload.assetId);
    expect(mp4Upload.jobId).not.toBe(mkvUpload.jobId);

    await expect(page.getByText("Processing...").first()).toBeVisible({
      timeout: 120_000,
    });
    await expect(page.getByText("Completed")).toHaveCount(2, {
      timeout: 600_000,
    });

    await page.getByTestId("sidebar-tab-search").click();
    const searchInput = page
      .getByTestId("search-input")
      .getByPlaceholder("Search Files");
    await expect(searchInput).toBeEnabled();
    await searchInput.fill("forklift");
    await page.getByTestId("search-button").click();

    const mp4AssetId = await verifySearchResultMedia(
      page,
      request,
      runtimeBaseUrl,
      media.mp4
    );
    const mkvAssetId = await verifySearchResultMedia(
      page,
      request,
      runtimeBaseUrl,
      media.mkv
    );
    expect(mp4AssetId).toBe(mp4Upload.assetId);
    expect(mkvAssetId).toBe(mkvUpload.assetId);
    expect(mp4Upload.assetId).not.toBe(mkvUpload.assetId);
  });

  test("shows a real failed job and retries the same recorded-video job", async ({
    page,
    runtimeBaseUrl,
  }, testInfo) => {
    const media = await createRecordedVideoFixtures(testInfo.outputDir);

    await page.goto(runtimeBaseUrl);
    const [complete] = await captureCompletedUploads(page, 1, () =>
      chooseRecordedVideos(page, [media.corruptMkv])
    );
    expect(complete.filename).toBe(media.corruptMkvName);

    await expect(
      page.getByText("Recorded video processing failed")
    ).toBeVisible({ timeout: 180_000 });
    await expect(page.getByText("1 failed")).toBeVisible();

    const retried = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === `${complete.statusUrl}/retry`
    );
    await page
      .getByRole("button", { name: `Retry ${media.corruptMkvName}` })
      .click();
    const retriedResponse = await retried;
    expect(retriedResponse.request().postData()).toBeNull();
    expect(retriedResponse.status()).toBe(200);
    const retryPayload = (await retriedResponse.json()) as {
      asset_id?: unknown;
      job_id?: unknown;
      status?: unknown;
    };
    expect(retryPayload.asset_id).toBe(complete.assetId);
    expect(retryPayload.job_id).toBe(complete.jobId);
    expect(retryPayload.status).toBe("queued");
    await expect(page.getByText("Processing...")).toBeVisible();
    await expect(
      page.getByText("Recorded video processing failed")
    ).toBeVisible({ timeout: 180_000 });
  });

  test("cancels a real processing job from the upload progress dialog", async ({
    page,
    providerControlUrl,
    request,
    runtimeBaseUrl,
  }, testInfo) => {
    const media = await createRecordedVideoFixtures(testInfo.outputDir);

    await page.goto(runtimeBaseUrl);
    const armed = await request.post(
      `${providerControlUrl}/control/block-next-vision`,
      { data: {} }
    );
    expect(armed.status()).toBe(200);
    expect(await armed.json()).toEqual({
      block_next_vision: true,
      blocked_vision_requests: 0,
    });
    try {
      const [complete] = await captureCompletedUploads(page, 1, () =>
        chooseRecordedVideos(page, [media.cancelMkv])
      );
      expect(complete.filename).toBe(path.basename(media.cancelMkv));

      await expect(page.getByText("Processing...")).toBeVisible({
        timeout: 120_000,
      });
      const cancelButton = page.getByRole("button", { name: "Cancel All" });
      await expect(cancelButton).toBeVisible();
      await expect(cancelButton).toBeEnabled();

      await expect
        .poll(
          async () => {
            const state = await request.get(
              `${providerControlUrl}/control/state`
            );
            return (await state.json()).blocked_vision_requests;
          },
          { timeout: 120_000 }
        )
        .toBe(1);
      const statusEndpoint = new URL(
        complete.statusUrl,
        runtimeBaseUrl
      ).toString();
      await expect
        .poll(async () => {
          const response = await request.get(statusEndpoint);
          const payload = (await response.json()) as {
            asset_id?: unknown;
            job_id?: unknown;
            status?: unknown;
          };
          expect(payload.asset_id).toBe(complete.assetId);
          expect(payload.job_id).toBe(complete.jobId);
          return payload.status;
        })
        .toBe("running");

      const cancelled = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname === `${complete.statusUrl}/cancel`
      );
      await cancelButton.click();
      const cancelledResponse = await cancelled;
      expect(cancelledResponse.request().method()).toBe("POST");
      expect(new URL(cancelledResponse.request().url()).pathname).toBe(
        `${complete.statusUrl}/cancel`
      );
      expect(cancelledResponse.request().postData()).toBeNull();
      expect(cancelledResponse.status()).toBe(200);
      const cancelPayload = (await cancelledResponse.json()) as {
        asset_id?: unknown;
        job_id?: unknown;
        status?: unknown;
      };
      expect(cancelPayload.asset_id).toBe(complete.assetId);
      expect(cancelPayload.job_id).toBe(complete.jobId);
      expect(cancelPayload.status).toBe("running");

      const released = await request.post(
        `${providerControlUrl}/control/release`,
        { data: {} }
      );
      expect(released.status()).toBe(200);
      await expect
        .poll(async () => {
          const response = await request.get(statusEndpoint);
          return ((await response.json()) as { status?: unknown }).status;
        })
        .toBe("cancelled");
      await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
      await expect(page.getByText("1 cancelled")).toBeVisible();
    } finally {
      await request.post(`${providerControlUrl}/control/release`, {
        data: {},
      });
    }
  });
}
