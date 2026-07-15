// SPDX-License-Identifier: MIT

export type RecordedVideoJobStatus =
  | 'queued'
  | 'running'
  | 'retry_wait'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface CompletedUpload {
  asset_id: string;
  job_id: string;
  status: RecordedVideoJobStatus;
  status_url: string;
}

export interface JobStatusResponse {
  asset_id: string;
  job_id: string;
  status: RecordedVideoJobStatus;
  stage: string | null;
  attempt: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
  heartbeat_at: string | null;
}

type FetchImplementation = typeof fetch;

export interface PollRecordedVideoJobOptions {
  agentApiUrl?: string;
  signal?: AbortSignal;
  intervalMs?: number;
  fetchImpl?: FetchImplementation;
  sleep?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
  onStatus?: (job: JobStatusResponse) => void;
}

export interface RecordedVideoJobActionOptions {
  agentApiUrl?: string;
  signal?: AbortSignal;
  fetchImpl?: FetchImplementation;
}

const STATUSES: ReadonlySet<string> = new Set([
  'queued',
  'running',
  'retry_wait',
  'completed',
  'failed',
  'cancelled',
]);

const ACTIVE_STATUSES: ReadonlySet<RecordedVideoJobStatus> = new Set([
  'queued',
  'running',
  'retry_wait',
]);

function abortError(): Error {
  if (typeof DOMException !== 'undefined') {
    return new DOMException('Video processing status request was cancelled', 'AbortError');
  }
  const error = new Error('Video processing status request was cancelled');
  error.name = 'AbortError';
  return error;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw abortError();
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function parseStatus(value: unknown): RecordedVideoJobStatus {
  if (!requireString(value) || !STATUSES.has(value)) {
    if (requireString(value)) {
      throw new Error(`Video processing returned unsupported job status: ${value}`);
    }
    throw new Error('Video processing returned an invalid response');
  }
  return value as RecordedVideoJobStatus;
}

export function parseCompletedUpload(value: unknown): CompletedUpload {
  if (!isObject(value)) {
    throw new Error('Video processing returned an invalid response');
  }
  const status = parseStatus(value.status);
  if (
    !requireString(value.asset_id) ||
    !requireString(value.job_id) ||
    !requireString(value.status_url)
  ) {
    throw new Error('Video processing returned an invalid response');
  }
  return {
    asset_id: value.asset_id,
    job_id: value.job_id,
    status,
    status_url: value.status_url,
  };
}

export function parseJobStatusResponse(value: unknown): JobStatusResponse {
  if (!isObject(value)) {
    throw new Error('Video processing returned an invalid response');
  }
  const status = parseStatus(value.status);
  if (
    !requireString(value.asset_id) ||
    !requireString(value.job_id) ||
    typeof value.attempt !== 'number' ||
    !Number.isInteger(value.attempt) ||
    value.attempt < 0 ||
    !requireString(value.created_at) ||
    !requireString(value.updated_at) ||
    !(value.stage === null || typeof value.stage === 'string') ||
    !(value.error === null || typeof value.error === 'string') ||
    !(value.next_run_at === null || typeof value.next_run_at === 'string') ||
    !(value.heartbeat_at === null || typeof value.heartbeat_at === 'string')
  ) {
    throw new Error('Video processing returned an invalid response');
  }
  return {
    asset_id: value.asset_id,
    job_id: value.job_id,
    status,
    stage: value.stage,
    attempt: value.attempt,
    error: value.error,
    created_at: value.created_at,
    updated_at: value.updated_at,
    next_run_at: value.next_run_at,
    heartbeat_at: value.heartbeat_at,
  };
}

async function readJson(response: Response, context: string): Promise<unknown> {
  if (!response.ok) {
    throw new Error(`${context} (HTTP ${response.status})`);
  }
  try {
    return await response.json();
  } catch {
    throw new Error('Video processing returned an invalid response');
  }
}

export function resolveRecordedVideoJobUrl(statusUrl: string, agentApiUrl?: string): string {
  if (/^https?:\/\//i.test(statusUrl)) {
    return statusUrl;
  }
  if (agentApiUrl && /^https?:\/\//i.test(agentApiUrl)) {
    return new URL(statusUrl, agentApiUrl).toString();
  }
  return statusUrl;
}

function defaultSleep(milliseconds: number, signal?: AbortSignal): Promise<void> {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        reject(abortError());
      },
      { once: true },
    );
  });
}

export async function pollRecordedVideoJob(
  statusUrl: string,
  options: PollRecordedVideoJobOptions = {},
): Promise<JobStatusResponse> {
  const fetchImpl = options.fetchImpl ?? fetch;
  const sleep = options.sleep ?? defaultSleep;
  const url = resolveRecordedVideoJobUrl(statusUrl, options.agentApiUrl);

  while (true) {
    throwIfAborted(options.signal);
    const response = await fetchImpl(url, { signal: options.signal });
    const job = parseJobStatusResponse(
      await readJson(response, 'Unable to read video processing status'),
    );
    options.onStatus?.(job);
    if (!ACTIVE_STATUSES.has(job.status)) {
      return job;
    }
    await sleep(options.intervalMs ?? 1000, options.signal);
  }
}

async function postJobAction(
  jobId: string,
  action: 'retry' | 'cancel',
  options: RecordedVideoJobActionOptions,
): Promise<JobStatusResponse> {
  throwIfAborted(options.signal);
  const base = (options.agentApiUrl ?? '/api/v1').replace(/\/$/, '');
  const url = `${base}/jobs/${encodeURIComponent(jobId)}/${action}`;
  const response = await (options.fetchImpl ?? fetch)(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: options.signal,
  });
  return parseJobStatusResponse(
    await readJson(response, `Unable to ${action} video processing`),
  );
}

export function retryRecordedVideoJob(
  jobId: string,
  options: RecordedVideoJobActionOptions = {},
): Promise<JobStatusResponse> {
  return postJobAction(jobId, 'retry', options);
}

export function cancelRecordedVideoJob(
  jobId: string,
  options: RecordedVideoJobActionOptions = {},
): Promise<JobStatusResponse> {
  return postJobAction(jobId, 'cancel', options);
}
