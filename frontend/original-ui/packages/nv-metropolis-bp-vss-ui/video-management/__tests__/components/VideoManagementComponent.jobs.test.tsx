// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  cancelRecordedVideoJob,
  pollRecordedVideoJob,
  retryRecordedVideoJob,
} from '@nemo-agent-toolkit/ui';
import { VideoManagementComponent } from '../../lib-src/VideoManagementComponent';
import { chunkedUpload, notifyUploadComplete } from '../../lib-src/chunkedUpload';

const mockPollRecordedVideoJob = pollRecordedVideoJob as jest.Mock;
const mockRetryRecordedVideoJob = retryRecordedVideoJob as jest.Mock;
const mockCancelRecordedVideoJob = cancelRecordedVideoJob as jest.Mock;
const mockChunkedUpload = chunkedUpload as jest.Mock;
const mockNotifyUploadComplete = notifyUploadComplete as jest.Mock;

jest.mock('@nemo-agent-toolkit/ui', () => ({
  UploadFilesDialog: () => null,
  VideoModal: () => null,
  useVideoModal: () => ({
    videoModal: { isOpen: false, videoUrl: '', title: '' },
    openVideoModal: jest.fn(),
    closeVideoModal: jest.fn(),
  }),
  useChatVideoUploadCompleteSubscription: jest.fn(),
  pollRecordedVideoJob: jest.fn(),
  retryRecordedVideoJob: jest.fn(),
  cancelRecordedVideoJob: jest.fn(),
}));

jest.mock('../../lib-src/chunkedUpload', () => ({
  chunkedUpload: jest.fn(),
  notifyUploadComplete: jest.fn(),
}));

jest.mock('../../lib-src/hooks', () => ({
  useStreams: () => ({
    streams: [],
    isLoading: false,
    error: null,
    refetch: jest.fn(),
  }),
  useStorageTimelines: () => ({
    refetch: jest.fn(),
    getEndTimeForStream: jest.fn(),
    getLastTimelineForStream: jest.fn(),
  }),
}));

jest.mock('../../lib-src/api', () => ({
  createApiEndpoints: () => ({ UPLOAD_FILE: 'https://vst.example.com/storage/file' }),
}));

jest.mock('../../lib-src/components', () => {
  const React = require('react');
  const { UploadProgressPanel } = jest.requireActual(
    '../../lib-src/components/UploadProgressPanel',
  );
  return {
    UploadProgressPanel,
    Toolbar: ({ onFilesSelected }: { onFilesSelected: (files: File[]) => void }) =>
      React.createElement(
        'button',
        {
          type: 'button',
          onClick: () => onFilesSelected([
            new File(['video'], 'recorded.mp4', { type: 'video/mp4' }),
          ]),
        },
        'Choose recorded video',
      ),
    AgentUploadDialog: ({
      open,
      onConfirmUpload,
    }: {
      open: boolean;
      onConfirmUpload: () => void;
    }) => open
      ? React.createElement(
        'button',
        { type: 'button', onClick: onConfirmUpload },
        'Confirm upload',
      )
      : null,
    AddRtspDialog: () => null,
    DeleteConfirmDialog: () => null,
    EmptyState: () => null,
    LoadingState: () => null,
    StreamsGrid: () => null,
    VideoManagementSidebarControls: () => null,
  };
});

const acceptedJob = {
  asset_id: 'asset-1',
  job_id: 'job-1',
  status: 'queued' as const,
  status_url: '/api/v1/jobs/job-1',
};

const jobStatus = (
  status: 'queued' | 'running' | 'retry_wait' | 'completed' | 'failed' | 'cancelled',
  error: string | null = null,
) => ({
  asset_id: 'asset-1',
  job_id: 'job-1',
  status,
  stage: status,
  attempt: 1,
  error,
  created_at: '2026-07-15T01:00:00Z',
  updated_at: '2026-07-15T01:00:01Z',
  next_run_at: null,
  heartbeat_at: null,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderComponent() {
  return render(
    <VideoManagementComponent
      videoManagementData={{
        systemStatus: 'ok',
        vstApiUrl: 'https://vst.example.com/vst',
        agentApiUrl: 'https://agent.example.com/api/v1',
      }}
    />,
  );
}

async function startUpload() {
  fireEvent.click(screen.getByRole('button', { name: 'Choose recorded video' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm upload' }));
  await waitFor(() => expect(mockNotifyUploadComplete).toHaveBeenCalledTimes(1));
}

describe('VideoManagementComponent recorded video jobs', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockChunkedUpload.mockResolvedValue({ sensorId: 'asset-1' });
    mockNotifyUploadComplete.mockResolvedValue(acceptedJob);
    mockRetryRecordedVideoJob.mockResolvedValue(jobStatus('queued'));
    mockCancelRecordedVideoJob.mockResolvedValue(jobStatus('cancelled'));
  });

  it('keeps the upload processing until the backend job completes', async () => {
    const poll = deferred<ReturnType<typeof jobStatus>>();
    mockPollRecordedVideoJob.mockReturnValue(poll.promise);
    renderComponent();

    await startUpload();
    expect(await screen.findByText('Processing...')).toBeInTheDocument();
    expect(screen.queryByText('Completed')).not.toBeInTheDocument();
    expect(mockPollRecordedVideoJob).toHaveBeenCalledWith(
      acceptedJob.status_url,
      expect.objectContaining({
        agentApiUrl: 'https://agent.example.com/api/v1',
        signal: expect.any(AbortSignal),
      }),
    );

    await act(async () => poll.resolve(jobStatus('completed')));
    expect(await screen.findByText('Completed')).toBeInTheDocument();
  });

  it('shows the safe failed summary and retries the same job', async () => {
    mockPollRecordedVideoJob
      .mockResolvedValueOnce(jobStatus('failed', 'Recorded video processing failed'))
      .mockResolvedValueOnce(jobStatus('completed'));
    renderComponent();

    await startUpload();
    expect(await screen.findByText('Recorded video processing failed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry recorded.mp4' }));

    await waitFor(() => expect(mockRetryRecordedVideoJob).toHaveBeenCalledWith(
      'job-1',
      expect.objectContaining({ agentApiUrl: 'https://agent.example.com/api/v1' }),
    ));
    expect(await screen.findByText('Completed')).toBeInTheDocument();
    expect(mockPollRecordedVideoJob).toHaveBeenCalledTimes(2);
  });

  it('requests cancellation for a processing job when Cancel All is clicked', async () => {
    const poll = deferred<ReturnType<typeof jobStatus>>();
    mockPollRecordedVideoJob.mockReturnValue(poll.promise);
    renderComponent();

    await startUpload();
    await waitFor(() => expect(mockPollRecordedVideoJob).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel All' }));

    await waitFor(() => expect(mockCancelRecordedVideoJob).toHaveBeenCalledWith(
      'job-1',
      expect.objectContaining({ agentApiUrl: 'https://agent.example.com/api/v1' }),
    ));
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
  });

  it('aborts an active job poll when the component unmounts', async () => {
    const poll = deferred<ReturnType<typeof jobStatus>>();
    mockPollRecordedVideoJob.mockReturnValue(poll.promise);
    const view = renderComponent();

    await startUpload();
    await waitFor(() => expect(mockPollRecordedVideoJob).toHaveBeenCalledTimes(1));
    const signal = mockPollRecordedVideoJob.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    view.unmount();
    expect(signal.aborted).toBe(true);
  });
});
