// SPDX-License-Identifier: MIT
import {
  cancelRecordedVideoJob,
  pollRecordedVideoJob,
  resolveRecordedVideoJobUrl,
  retryRecordedVideoJob,
} from '../../lib-src/utils/recordedVideoJob';

const jsonResponse = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: status === 200 ? 'OK' : 'Bad Gateway',
  json: jest.fn().mockResolvedValue(body),
});

const job = (status: string, overrides: Record<string, unknown> = {}) => ({
  asset_id: 'asset-1',
  job_id: 'job-1',
  status,
  stage: status === 'completed' ? 'completed' : 'embedding',
  attempt: 1,
  error: null,
  created_at: '2026-07-15T01:00:00Z',
  updated_at: '2026-07-15T01:00:01Z',
  next_run_at: null,
  heartbeat_at: null,
  ...overrides,
});

describe('recorded video job URL resolution', () => {
  it('keeps same-origin relative status URLs in browser mode', () => {
    expect(resolveRecordedVideoJobUrl('/api/v1/jobs/job-1')).toBe('/api/v1/jobs/job-1');
  });

  it('resolves relative status URLs against an absolute agent API URL', () => {
    expect(
      resolveRecordedVideoJobUrl('/api/v1/jobs/job-1', 'https://agent.example.com/api/v1'),
    ).toBe('https://agent.example.com/api/v1/jobs/job-1');
  });

  it('preserves absolute status URLs', () => {
    expect(
      resolveRecordedVideoJobUrl(
        'https://jobs.example.com/api/v1/jobs/job-1',
        'https://agent.example.com/api/v1',
      ),
    ).toBe('https://jobs.example.com/api/v1/jobs/job-1');
  });
});

describe('pollRecordedVideoJob', () => {
  it('polls queued and running states until completed', async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(job('queued')))
      .mockResolvedValueOnce(jsonResponse(job('running')))
      .mockResolvedValueOnce(jsonResponse(job('completed')));
    const onStatus = jest.fn();

    const result = await pollRecordedVideoJob('/api/v1/jobs/job-1', {
      fetchImpl: fetchImpl as any,
      sleep: async () => undefined,
      onStatus,
    });

    expect(result.status).toBe('completed');
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(onStatus.mock.calls.map(([value]) => value.status)).toEqual([
      'queued',
      'running',
      'completed',
    ]);
  });

  it('continues polling retry_wait', async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(job('retry_wait', { attempt: 2 })))
      .mockResolvedValueOnce(jsonResponse(job('completed', { attempt: 2 })));

    const result = await pollRecordedVideoJob('/api/v1/jobs/job-1', {
      fetchImpl: fetchImpl as any,
      sleep: async () => undefined,
    });

    expect(result.status).toBe('completed');
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it.each(['failed', 'cancelled'])('returns terminal %s without another request', async (status) => {
    const fetchImpl = jest.fn().mockResolvedValue(
      jsonResponse(job(status, { error: status === 'failed' ? 'Recorded video processing failed' : null })),
    );

    const result = await pollRecordedVideoJob('/api/v1/jobs/job-1', {
      fetchImpl: fetchImpl as any,
      sleep: async () => undefined,
    });

    expect(result.status).toBe(status);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('fails closed for an unknown status', async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse(job('paused')));

    await expect(
      pollRecordedVideoJob('/api/v1/jobs/job-1', { fetchImpl: fetchImpl as any }),
    ).rejects.toThrow('unsupported job status');
  });

  it('converts HTTP, malformed JSON, and missing-field failures to safe errors', async () => {
    const httpFetch = jest.fn().mockResolvedValue(jsonResponse({}, 502));
    await expect(
      pollRecordedVideoJob('/api/v1/jobs/job-1', { fetchImpl: httpFetch as any }),
    ).rejects.toThrow('Unable to read video processing status (HTTP 502)');

    const malformedFetch = jest.fn().mockResolvedValue({
      ...jsonResponse({}),
      json: jest.fn().mockRejectedValue(new SyntaxError('secret response body')),
    });
    await expect(
      pollRecordedVideoJob('/api/v1/jobs/job-1', { fetchImpl: malformedFetch as any }),
    ).rejects.toThrow('invalid response');

    const missingFetch = jest.fn().mockResolvedValue(jsonResponse({ status: 'completed' }));
    await expect(
      pollRecordedVideoJob('/api/v1/jobs/job-1', { fetchImpl: missingFetch as any }),
    ).rejects.toThrow('invalid response');
  });

  it('honours AbortSignal before requesting or sleeping again', async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = jest.fn();

    await expect(
      pollRecordedVideoJob('/api/v1/jobs/job-1', {
        fetchImpl: fetchImpl as any,
        signal: controller.signal,
      }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe('recorded video job actions', () => {
  it.each([
    ['retry', retryRecordedVideoJob],
    ['cancel', cancelRecordedVideoJob],
  ])('POSTs %s and validates the returned job', async (action, invoke) => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse(job(action === 'retry' ? 'queued' : 'cancelled')));

    const result = await invoke('job-1', {
      agentApiUrl: 'https://agent.example.com/api/v1',
      fetchImpl: fetchImpl as any,
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      `https://agent.example.com/api/v1/jobs/job-1/${action}`,
      expect.objectContaining({ method: 'POST' }),
    );
    expect(result.job_id).toBe('job-1');
  });
});
