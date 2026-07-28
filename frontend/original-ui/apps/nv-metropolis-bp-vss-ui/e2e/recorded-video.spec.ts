// SPDX-License-Identifier: MIT

import type {
  APIRequestContext,
  ConsoleMessage,
  Page,
  Request,
  Response,
} from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";

const CHAT_QUESTION = "What safety risk is visible in the selected segment?";
const CHAT_FINAL_ANSWER =
  "The selected segment shows a forklift operating near a worker in an industrial area.";
const LIVE_PROVIDER = process.env.PLAYWRIGHT_LIVE_PROVIDER === "1";
const REAL_BUSINESS_VIDEO = (process.env.PLAYWRIGHT_REAL_VIDEO || "").trim();
const REAL_BUSINESS_QUERY =
  (process.env.PLAYWRIGHT_REAL_QUERY || "").trim() ||
  "forklift operating close to a pedestrian";
const CHAT_TRACE_ROOT =
  process.env.PLAYWRIGHT_CHAT_TRACE_ROOT ||
  path.resolve(
    __dirname,
    "../../../../..",
    ".runtime/es-stack/latest/chat-traces"
  );

type RequiredConceptGroup = {
  groupId: string;
  alternatives: readonly string[];
  negatedAlternatives: readonly string[];
};

type ForbiddenConceptGroup = {
  groupId: string;
  alternatives: readonly string[];
  negatedAlternatives?: readonly string[];
};

type BusinessAnswerEvaluation = {
  coverage: number;
  matchedGroupIds: string[];
  missedGroupIds: string[];
  forbiddenMatches: string[];
  passed: boolean;
};

const CLAUSE_BOUNDARY = /[.!?;|\n\r\u3002\uff01\uff1f\uff1b]+/u;
const CJK_CHARACTER = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/u;

function normalizeBusinessText(value: string): string {
  return value.toLowerCase().trim().split(/\s+/u).filter(Boolean).join(" ");
}

function splitBusinessClauses(value: string): string[] {
  return value
    .split(CLAUSE_BOUNDARY)
    .map(normalizeBusinessText)
    .filter(Boolean);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function containsBusinessPhrase(text: string, phrase: string): boolean {
  const normalizedPhrase = normalizeBusinessText(phrase);
  if (!normalizedPhrase) return false;
  if (CJK_CHARACTER.test(normalizedPhrase)) {
    return text.includes(normalizedPhrase);
  }
  return new RegExp(
    `(?<![a-z0-9_])${escapeRegExp(normalizedPhrase)}(?![a-z0-9_])`,
    "iu"
  ).test(text);
}

function evaluateBusinessAnswer(
  answer: string,
  requiredGroups: readonly RequiredConceptGroup[],
  forbiddenGroups: readonly ForbiddenConceptGroup[],
  minimumCoverage: number
): BusinessAnswerEvaluation {
  if (!requiredGroups.length) {
    throw new Error("At least one required concept group is required");
  }
  if (minimumCoverage < 0 || minimumCoverage > 1) {
    throw new Error("minimumCoverage must be between zero and one");
  }
  const clauses = splitBusinessClauses(answer);
  const matchedGroupIds = requiredGroups
    .filter((group) =>
      clauses.some(
        (clause) =>
          group.alternatives.some((alternative) =>
            containsBusinessPhrase(clause, alternative)
          ) &&
          !group.negatedAlternatives.some((alternative) =>
            containsBusinessPhrase(clause, alternative)
          )
      )
    )
    .map((group) => group.groupId);
  const matchedGroupIdSet = new Set(matchedGroupIds);
  const missedGroupIds = requiredGroups
    .filter((group) => !matchedGroupIdSet.has(group.groupId))
    .map((group) => group.groupId);
  const forbiddenMatches = forbiddenGroups
    .filter((group) =>
      clauses.some(
        (clause) =>
          group.alternatives.some((alternative) =>
            containsBusinessPhrase(clause, alternative)
          ) &&
          !(group.negatedAlternatives || []).some((alternative) =>
            containsBusinessPhrase(clause, alternative)
          )
      )
    )
    .map((group) => group.groupId);
  const coverage = matchedGroupIds.length / requiredGroups.length;
  return {
    coverage,
    matchedGroupIds,
    missedGroupIds,
    forbiddenMatches,
    passed: coverage >= minimumCoverage && forbiddenMatches.length === 0,
  };
}

const FORKLIFT_REQUIRED_CONCEPT_GROUPS: readonly RequiredConceptGroup[] = [
  {
    groupId: "forklift",
    alternatives: ["forklift", "lift truck", "叉车"],
    negatedAlternatives: ["no forklift", "no lift truck", "没有叉车"],
  },
  {
    groupId: "person",
    alternatives: ["person", "worker", "pedestrian", "人员", "工人", "行人"],
    negatedAlternatives: [
      "no person",
      "no worker",
      "no pedestrian",
      "没有人员",
      "没有工人",
      "没有行人",
      "无人",
    ],
  },
  {
    groupId: "proximity",
    alternatives: [
      "near",
      "close",
      "proximity",
      "shared area",
      "接近",
      "靠近",
      "同一区域",
    ],
    negatedAlternatives: [
      "not near",
      "not close",
      "far apart",
      "completely separated",
      "不接近",
      "不靠近",
      "远离",
      "完全隔离",
    ],
  },
];

const FORKLIFT_FORBIDDEN_CONCEPT_GROUPS: readonly ForbiddenConceptGroup[] = [
  {
    groupId: "no_forklift",
    alternatives: [
      "no forklift is present",
      "no lift truck is present",
      "没有叉车",
    ],
  },
  {
    groupId: "no_person",
    alternatives: [
      "no person is present",
      "no worker is present",
      "no pedestrian is present",
      "没有人员",
      "现场无人",
    ],
  },
  {
    groupId: "complete_separation",
    alternatives: [
      "forklift and pedestrians are completely separated",
      "叉车与行人完全隔离",
    ],
  },
];

if (process.env.JEST_WORKER_ID) {
  describe("business answer concept gate", () => {
    it("does not match person inside personal", () => {
      const evaluation = evaluateBusinessAnswer(
        "Personal protective equipment is visible.",
        FORKLIFT_REQUIRED_CONCEPT_GROUPS,
        FORKLIFT_FORBIDDEN_CONCEPT_GROUPS,
        0.8
      );

      expect(evaluation.matchedGroupIds).toEqual([]);
      expect(evaluation.forbiddenMatches).toEqual([]);
      expect(evaluation.passed).toBe(false);
    });

    it("rejects negated concepts and grouped forbidden conclusions", () => {
      const evaluation = evaluateBusinessAnswer(
        "No person is present and no forklift is present; they are not near each other.",
        FORKLIFT_REQUIRED_CONCEPT_GROUPS,
        FORKLIFT_FORBIDDEN_CONCEPT_GROUPS,
        0.8
      );

      expect(evaluation.matchedGroupIds).toEqual([]);
      expect(evaluation.forbiddenMatches).toEqual(["no_forklift", "no_person"]);
      expect(evaluation.passed).toBe(false);
    });

    it("accepts later positive evidence in a separate clause", () => {
      const evaluation = evaluateBusinessAnswer(
        "Initially no person is visible; a person then enters near a forklift.",
        FORKLIFT_REQUIRED_CONCEPT_GROUPS,
        FORKLIFT_FORBIDDEN_CONCEPT_GROUPS,
        1
      );

      expect(evaluation.matchedGroupIds).toEqual([
        "forklift",
        "person",
        "proximity",
      ]);
      expect(evaluation.passed).toBe(true);
    });

    it("matches explicit CJK phrases with clause-level negation", () => {
      const evaluation = evaluateBusinessAnswer(
        "起初没有工人；随后人员靠近叉车。",
        FORKLIFT_REQUIRED_CONCEPT_GROUPS,
        FORKLIFT_FORBIDDEN_CONCEPT_GROUPS,
        1
      );

      expect(evaluation.matchedGroupIds).toEqual([
        "forklift",
        "person",
        "proximity",
      ]);
      expect(evaluation.passed).toBe(true);
    });

    it("ignores a forbidden conclusion negated in the same clause", () => {
      const evaluation = evaluateBusinessAnswer(
        "A person performs routine work; 未见正在发生碰撞。",
        [
          {
            groupId: "person",
            alternatives: ["person"],
            negatedAlternatives: ["no person"],
          },
          {
            groupId: "routine",
            alternatives: ["routine"],
            negatedAlternatives: ["not routine"],
          },
        ],
        [
          {
            groupId: "collision",
            alternatives: ["正在发生碰撞"],
            negatedAlternatives: ["未见正在发生碰撞"],
          },
        ],
        1
      );

      expect(evaluation.forbiddenMatches).toEqual([]);
      expect(evaluation.passed).toBe(true);
    });
  });

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

  type PageDiagnostics = {
    assertClean: () => void;
    dispose: () => void;
  };

  function capturePageDiagnostics(page: Page): PageDiagnostics {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const networkFailures: string[] = [];
    const serverErrors: string[] = [];
    const mediaAborts: Array<{ path: string; message: string }> = [];
    const mediaStatuses = new Map<string, Set<number>>();
    const mediaPathPattern = /^\/api\/v1\/vst\/v1\/storage\/file\/[^/]+$/;
    const captureConsoleError = (message: ConsoleMessage) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    };
    const capturePageError = (error: Error) => pageErrors.push(error.message);
    const captureRequestFailure = (request: Request) => {
      const failure = request.failure()?.errorText || "unknown failure";
      const url = new URL(request.url());
      const message = `${request.method()} ${request.url()}: ${failure}`;
      if (
        request.method() === "GET" &&
        failure === "net::ERR_ABORTED" &&
        mediaPathPattern.test(url.pathname)
      ) {
        mediaAborts.push({ path: url.pathname, message });
        return;
      }
      networkFailures.push(message);
    };
    const captureResponse = (response: Response) => {
      if (response.status() >= 500) {
        serverErrors.push(`${response.status()} ${response.url()}`);
      }
      const path = new URL(response.url()).pathname;
      if (
        mediaPathPattern.test(path) &&
        [200, 206].includes(response.status())
      ) {
        const statuses = mediaStatuses.get(path) || new Set<number>();
        statuses.add(response.status());
        mediaStatuses.set(path, statuses);
      }
    };

    page.on("console", captureConsoleError);
    page.on("pageerror", capturePageError);
    page.on("requestfailed", captureRequestFailure);
    page.on("response", captureResponse);
    return {
      assertClean: () => {
        const unexplainedMediaAborts = mediaAborts
          .filter(({ path }) => {
            const statuses = mediaStatuses.get(path);
            return !statuses?.has(200) && !statuses?.has(206);
          })
          .map(({ message }) => message);
        expect(consoleErrors).toEqual([]);
        expect(pageErrors).toEqual([]);
        expect(networkFailures).toEqual([]);
        expect(serverErrors).toEqual([]);
        expect(unexplainedMediaAborts).toEqual([]);
      },
      dispose: () => {
        page.off("console", captureConsoleError);
        page.off("pageerror", capturePageError);
        page.off("requestfailed", captureRequestFailure);
        page.off("response", captureResponse);
      },
    };
  }

  async function verifyRealProviderEvidence(
    request: APIRequestContext,
    runtimeBaseUrl: string
  ): Promise<void> {
    const response = await request.get(
      `${runtimeBaseUrl}/api/v1/runtime/evidence`
    );
    expect(response.status()).toBe(200);
    const evidence = (await response.json()) as {
      real_provider_ready?: unknown;
      config_fingerprint?: unknown;
      roles?: Record<string, { is_mock?: unknown } | null>;
      search?: {
        allow_mock_fallback?: unknown;
        force_mock_embedding?: unknown;
      };
    };
    expect(evidence.real_provider_ready).toBe(true);
    expect(
      requiredString(evidence.config_fingerprint, "config_fingerprint")
    ).toMatch(/^[0-9a-f]{64}$/);
    for (const role of ["llm", "vlm", "embedding"]) {
      expect(evidence.roles?.[role]?.is_mock).toBe(false);
    }
    expect(evidence.search?.allow_mock_fallback).toBe(false);
    expect(evidence.search?.force_mock_embedding).toBe(false);
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
    action: () => Promise<void>,
    onAssetCreated?: (assetId: string) => void
  ): Promise<CompletedUploadEvidence[]> {
    const responses: Response[] = [];
    const assetRegistrations: Promise<void>[] = [];
    const capture = (response: Response) => {
      const pathname = new URL(response.url()).pathname;
      if (
        onAssetCreated &&
        response.request().method() === "POST" &&
        response.ok() &&
        pathname === "/api/v1/videos"
      ) {
        assetRegistrations.push(
          response.json().then((payload: { asset_id?: unknown }) => {
            onAssetCreated(
              requiredString(payload.asset_id, "created asset_id")
            );
          })
        );
      }
      if (
        response.request().method() === "POST" &&
        response.status() === 202 &&
        /^\/api\/v1\/videos\/[^/]+\/complete$/.test(pathname)
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
      await Promise.all(assetRegistrations);
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

  async function readNonEmptyFile(
    filePath: string,
    timeout: number
  ): Promise<string> {
    let content = "";
    await expect
      .poll(
        async () => {
          try {
            content = await readFile(filePath, "utf8");
            return content.trim().length;
          } catch {
            return 0;
          }
        },
        { timeout }
      )
      .toBeGreaterThan(0);
    return content;
  }

  async function verifyChatTrace(
    traceId: string,
    expectedAssetId: string,
    expectedSegmentId: string
  ): Promise<void> {
    expect(traceId).toMatch(/^[A-Za-z0-9_-]{1,255}$/);
    const traceDirectory = path.join(CHAT_TRACE_ROOT, traceId);
    const requestPayload = JSON.parse(
      await readNonEmptyFile(path.join(traceDirectory, "request.json"), 30_000)
    ) as Record<string, unknown>;
    expect(requestPayload.selected_asset_id).toBe(expectedAssetId);
    expect(requestPayload.selected_segment_id).toBe(expectedSegmentId);

    const tracePath = path.join(traceDirectory, "trace.jsonl");
    let traceText = "";
    await expect
      .poll(
        async () => {
          try {
            traceText = await readFile(tracePath, "utf8");
          } catch {
            traceText = "";
          }
          return traceText.includes('"event_type": "top_agent.final"');
        },
        { timeout: 30_000 }
      )
      .toBe(true);

    const events = traceText
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    const eventTypes = events.map((event) => String(event.event_type || ""));
    for (const requiredEvent of [
      "original_ui.chat.request",
      "top_agent.tool.call",
      "video_understanding.result",
      "top_agent.tool.result",
      "top_agent.final",
    ]) {
      expect(eventTypes).toContain(requiredEvent);
    }

    const videoToolCalls = events.filter(
      (event) =>
        event.event_type === "top_agent.tool.call" &&
        (event.payload as Record<string, unknown> | undefined)?.tool_name ===
          "video_understanding"
    );
    expect(videoToolCalls).toHaveLength(1);
    const finalEvents = events.filter(
      (event) => event.event_type === "top_agent.final"
    );
    expect(finalEvents).toHaveLength(1);
    expect(
      requiredString(
        (finalEvents[0].payload as Record<string, unknown> | undefined)
          ?.final_answer,
        "top_agent.final answer"
      )
    ).not.toBe("");
    expect(
      eventTypes.filter((eventType) => /(?:^|[._])error$/.test(eventType))
    ).toEqual([]);
    expect(traceText).not.toMatch(
      /Traceback|Failed to fetch|api_key client option/i
    );
  }

  async function verifySearchResultChat(
    page: Page,
    runtimeBaseUrl: string,
    fixturePath: string,
    expectedAssetId: string,
    expectedJobId: string
  ): Promise<void> {
    const filename = path.basename(fixturePath);
    const result = page.getByTestId("search-result-card").filter({
      has: page.getByRole("button", {
        name: `Play ${filename}`,
        exact: true,
      }),
    });
    await expect(result).toHaveCount(1);

    const addToChat = result.getByRole("button", {
      name: "+ Chat",
      exact: true,
    });
    await expect(addToChat).toBeVisible({ timeout: 30_000 });
    await addToChat.click();
    await expect(
      result.getByRole("button", { name: "Added", exact: true })
    ).toBeVisible();

    const openChat = page.getByTestId("chat-sidebar-open");
    if (await openChat.isVisible()) await openChat.click();

    await expect(
      page.getByTitle(`${filename} (media/video)`, { exact: true })
    ).toBeVisible();
    const textarea = page.locator('[data-testid="chat-textarea"]:visible');
    await expect(textarea).toBeVisible();
    await textarea.fill(CHAT_QUESTION);

    const chatResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/chat"
    );
    await textarea.press("Enter");
    const chatResponse = await chatResponsePromise;

    expect(chatResponse.status()).toBe(200);
    expect(new URL(chatResponse.url()).origin).toBe(
      new URL(runtimeBaseUrl).origin
    );
    const requestBody = chatResponse.request().postDataJSON() as {
      messages?: Array<{ role?: unknown; content?: unknown }>;
    };
    const latestUserMessage = requestBody.messages
      ?.filter((message) => message.role === "user")
      .at(-1);
    const userContent = requiredString(
      latestUserMessage?.content,
      "Chat user message content"
    );
    const contextMatch = /^\[Context: (.+)\]\n\n([^]+)$/.exec(userContent);
    expect(contextMatch).not.toBeNull();
    const contextItems = JSON.parse(contextMatch![1]) as Array<
      Record<string, unknown>
    >;
    expect(contextItems).toHaveLength(1);
    const context = contextItems[0];
    expect(context.assetId).toBe(expectedAssetId);
    const selectedSegmentId = requiredString(context.segmentId, "segmentId");
    expect(selectedSegmentId).not.toBe("");
    expect(context.jobId).toBe(expectedJobId);
    expect(context.videoName).toBe(filename);
    expect(requiredString(context.startTime, "startTime")).not.toBe("");
    expect(requiredString(context.endTime, "endTime")).not.toBe("");
    expect(context).not.toHaveProperty("video_path");
    expect(context).not.toHaveProperty("videoPath");
    expect(contextMatch![2]).toBe(CHAT_QUESTION);

    const assistantMessages = page.locator(
      '[data-testid="chat-message-assistant"]:visible'
    );
    if (LIVE_PROVIDER) {
      await expect
        .poll(
          async () =>
            ((await assistantMessages.last().textContent()) || "").trim(),
          { timeout: 180_000 }
        )
        .not.toBe("");
    } else {
      const answer = assistantMessages.filter({
        hasText: CHAT_FINAL_ANSWER,
      });
      await expect(answer).toHaveCount(1, { timeout: 120_000 });
      await expect(answer).toBeVisible();
    }
    await expect(
      page.locator('[data-testid="chat-loading-spinner"]:visible')
    ).toBeHidden({ timeout: LIVE_PROVIDER ? 180_000 : 30_000 });
    const finalRenderedAnswer = (
      (await assistantMessages.last().textContent()) || ""
    ).trim();
    expect(finalRenderedAnswer).not.toBe("");
    expect(finalRenderedAnswer).not.toMatch(
      /(?:^|\b)(?:error|failed to fetch|api_key)(?:\b|:)/i
    );
    const traceId = requiredString(
      chatResponse.headers()["x-vsa-trace-id"],
      "X-VSA-Trace-ID"
    );
    await verifyChatTrace(traceId, expectedAssetId, selectedSegmentId);
  }

  async function deleteAssetAndVerifyRemoval(
    request: APIRequestContext,
    runtimeBaseUrl: string,
    assetId: string,
    searchQuery: string
  ): Promise<void> {
    const deleteUrl = `${runtimeBaseUrl}/api/v1/videos/${encodeURIComponent(
      assetId
    )}`;
    await expect
      .poll(
        async () => {
          const response = await request.delete(deleteUrl);
          expect([202, 204]).toContain(response.status());
          return response.status();
        },
        { timeout: 120_000 }
      )
      .toBe(204);

    const mediaResponse = await request.get(
      `${runtimeBaseUrl}/api/v1/vst/v1/storage/file/${encodeURIComponent(
        assetId
      )}`,
      { headers: { Range: "bytes=0-9" } }
    );
    expect([404, 410]).toContain(mediaResponse.status());

    await expect
      .poll(
        async () => {
          const response = await request.post(
            `${runtimeBaseUrl}/api/v1/search`,
            {
              data: {
                query: searchQuery,
                source_type: "video_file",
                top_k: 20,
                agent_mode: false,
              },
            }
          );
          expect(response.status()).toBe(200);
          const payload = (await response.json()) as {
            data?: Array<{ asset_id?: unknown }>;
          };
          return (payload.data || []).some(
            (result) => result.asset_id === assetId
          );
        },
        { timeout: 120_000, intervals: [1_000, 2_000, 5_000] }
      )
      .toBe(false);
  }

  async function cleanupCreatedAssets(
    request: APIRequestContext,
    runtimeBaseUrl: string,
    assetIds: ReadonlySet<string>,
    searchQuery: string
  ): Promise<void> {
    const failures: string[] = [];
    for (const assetId of assetIds) {
      try {
        await deleteAssetAndVerifyRemoval(
          request,
          runtimeBaseUrl,
          assetId,
          searchQuery
        );
      } catch (error) {
        failures.push(
          `${assetId}: ${
            error instanceof Error ? error.message : String(error)
          }`
        );
      }
    }
    if (failures.length) {
      throw new Error(`Recorded-video cleanup failed:\n${failures.join("\n")}`);
    }
  }

  test("uploads, searches, plays and chats with MP4 and MKV recorded-video segments", async ({
    page,
    request,
    runtimeBaseUrl,
  }, testInfo) => {
    const media = await createRecordedVideoFixtures(testInfo.outputDir);
    const diagnostics = capturePageDiagnostics(page);

    try {
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
        throw new Error(
          "MP4 and MKV completion responses must both be captured"
        );
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
      await verifySearchResultChat(
        page,
        runtimeBaseUrl,
        media.mp4,
        mp4Upload.assetId,
        mp4Upload.jobId
      );
      diagnostics.assertClean();
    } finally {
      diagnostics.dispose();
    }
  });

  test("validates a real forklift business video through the original UI", async ({
    page,
    request,
    runtimeBaseUrl,
  }) => {
    test.skip(
      !REAL_BUSINESS_VIDEO || !LIVE_PROVIDER,
      "Set PLAYWRIGHT_REAL_VIDEO and PLAYWRIGHT_LIVE_PROVIDER=1 to run the real-provider UI gate."
    );

    const diagnostics = capturePageDiagnostics(page);
    let upload: CompletedUploadEvidence | undefined;
    const createdAssetIds = new Set<string>();

    try {
      await verifyRealProviderEvidence(request, runtimeBaseUrl);
      await page.goto(runtimeBaseUrl);
      [upload] = await captureCompletedUploads(
        page,
        1,
        () => chooseRecordedVideos(page, [REAL_BUSINESS_VIDEO]),
        (assetId) => createdAssetIds.add(assetId)
      );
      expect(upload.filename).toBe(path.basename(REAL_BUSINESS_VIDEO));
      expect(createdAssetIds.has(upload.assetId)).toBe(true);
      await expect(page.getByText("Processing...")).toBeVisible({
        timeout: 120_000,
      });
      await expect(page.getByText("Completed")).toBeVisible({
        timeout: 600_000,
      });

      await page.getByTestId("sidebar-tab-search").click();
      const searchInput = page
        .getByTestId("search-input")
        .getByPlaceholder("Search Files");
      await expect(searchInput).toBeEnabled();
      await searchInput.fill(REAL_BUSINESS_QUERY);
      await page.getByTestId("search-button").click();

      const assetId = await verifySearchResultMedia(
        page,
        request,
        runtimeBaseUrl,
        REAL_BUSINESS_VIDEO
      );
      expect(assetId).toBe(upload.assetId);
      await verifySearchResultChat(
        page,
        runtimeBaseUrl,
        REAL_BUSINESS_VIDEO,
        upload.assetId,
        upload.jobId
      );

      const answer =
        (await page
          .locator('[data-testid="chat-message-assistant"]:visible')
          .last()
          .textContent()) || "";
      const answerEvaluation = evaluateBusinessAnswer(
        answer,
        FORKLIFT_REQUIRED_CONCEPT_GROUPS,
        FORKLIFT_FORBIDDEN_CONCEPT_GROUPS,
        1
      );
      expect(answerEvaluation).toMatchObject({
        coverage: 1,
        matchedGroupIds: ["forklift", "person", "proximity"],
        missedGroupIds: [],
        forbiddenMatches: [],
        passed: true,
      });
      diagnostics.assertClean();
    } finally {
      try {
        await cleanupCreatedAssets(
          request,
          runtimeBaseUrl,
          createdAssetIds,
          REAL_BUSINESS_QUERY
        );
      } finally {
        diagnostics.dispose();
      }
    }
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
