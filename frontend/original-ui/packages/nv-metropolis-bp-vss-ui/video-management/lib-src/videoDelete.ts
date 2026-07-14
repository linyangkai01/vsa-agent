// SPDX-License-Identifier: MIT
/**
 * Delete uploaded video via Agent API.
 *
 * Backend: DELETE /api/v1/videos/{video_id}
 * Handles VST (sensor + storage) and in "search" mode also ES + RTVI-CV.
 */

export interface DeleteVideoResult {
  status: string;
  message: string;
  video_id: string;
}

interface PendingDeleteResponse {
  status?: string;
  pending?: boolean;
  retry_after_ms?: number;
}

const MAX_DELETE_ATTEMPTS = 20;
const DEFAULT_RETRY_AFTER_MS = 250;

function waitForRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(new Error('Delete video was cancelled'));
  }
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timeoutId);
      reject(new Error('Delete video was cancelled'));
    };
    const timeoutId = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, delayMs);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

async function readJson<T>(response: Response): Promise<T | undefined> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error('Delete video returned an invalid JSON response');
  }
}

/**
 * Delete an uploaded video by sensor/video ID (UUID) via Agent API.
 * DELETE /api/v1/videos/{video_id}
 *
 * @param agentApiUrl - Base URL of the agent API (e.g., http://<IP>:8000/api/v1)
 * @param videoId - The sensor/video UUID (e.g., from the upload response)
 * @param signal - Optional AbortSignal for cancellation
 */
export async function deleteVideo(
  agentApiUrl: string,
  videoId: string,
  signal?: AbortSignal
): Promise<DeleteVideoResult> {
  for (let attempt = 0; attempt < MAX_DELETE_ATTEMPTS; attempt += 1) {
    if (signal?.aborted) {
      throw new Error('Delete video was cancelled');
    }

    const response = await fetch(`${agentApiUrl}/videos/${encodeURIComponent(videoId)}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
      signal,
    });

    if (response.status === 204) {
      return { status: 'completed', message: '', video_id: videoId };
    }

    const result = await readJson<DeleteVideoResult & PendingDeleteResponse>(response);
    const isPending =
      response.status === 202 ||
      (response.ok && (result?.status === 'pending' || result?.pending === true));
    if (isPending) {
      if (
        result &&
        ((result.status !== undefined && result.status !== 'pending') ||
          (result.pending !== undefined && result.pending !== true))
      ) {
        throw new Error('Delete video returned an invalid pending response');
      }
      if (attempt === MAX_DELETE_ATTEMPTS - 1) {
        break;
      }
      const retryAfterMs = result?.retry_after_ms;
      await waitForRetry(
        typeof retryAfterMs === 'number' && retryAfterMs >= 0
          ? Math.min(retryAfterMs, 1000)
          : DEFAULT_RETRY_AFTER_MS,
        signal
      );
      continue;
    }

    if (!response.ok) {
      throw new Error(
        result?.message || `Failed to delete video: ${response.statusText || response.status}`
      );
    }
    if (!result) {
      throw new Error('Delete video returned an unexpected success response');
    }
    if (result.status === 'failure') {
      throw new Error(result.message || `Failed to delete video: ${result.video_id}`);
    }
    if (result.status === 'completed' || result.status === 'success') {
      return result;
    }
    throw new Error('Delete video returned an unexpected success response');
  }

  throw new Error('Timed out waiting for video deletion to complete');
}
