// SPDX-License-Identifier: MIT
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  cancelRecordedVideoJob,
  pollRecordedVideoJob,
  retryRecordedVideoJob,
  uploadFileChunked,
} from '@aiqtoolkit-ui/common';
import { ChatFileUpload } from '@/components/Chat/ChatFileUpload';
import HomeContext from '@/pages/api/home/home.context';

const mockUploadFileChunked = uploadFileChunked as jest.Mock;
const mockPollRecordedVideoJob = pollRecordedVideoJob as jest.Mock;
const mockRetryRecordedVideoJob = retryRecordedVideoJob as jest.Mock;
const mockCancelRecordedVideoJob = cancelRecordedVideoJob as jest.Mock;

jest.mock('react-hot-toast', () => ({
  __esModule: true,
  default: { error: jest.fn(), success: jest.fn() },
}));

jest.mock('@aiqtoolkit-ui/common', () => ({
  UploadFilesDialog: ({
    open,
    onConfirm,
  }: {
    open?: boolean;
    onConfirm: (entries: Array<{
      id: string;
      file: File;
      formData: Record<string, unknown>;
      uploadFilename: string;
    }>) => void;
  }) => open ? (
    <button
      type="button"
      onClick={() => onConfirm([{
        id: 'file-1',
        file: new File(['video'], 'recorded.mp4', { type: 'video/mp4' }),
        formData: {},
        uploadFilename: 'recorded.mp4',
      }])}
    >
      Confirm upload
    </button>
  ) : null,
  copyToClipboard: jest.fn(async () => true),
  uploadFileChunked: jest.fn(),
  pollRecordedVideoJob: jest.fn(),
  retryRecordedVideoJob: jest.fn(),
  cancelRecordedVideoJob: jest.fn(),
}));

const acceptedUpload = {
  id: 'asset-1',
  filename: 'recorded.mp4',
  bytes: 5,
  video_id: 'asset-1',
  streamId: 'asset-1',
  filePath: '/recorded.mp4',
  timestamp: '2026-07-15T01:00:00Z',
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
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

const homeContextValue = {
  state: {
    agentApiUrlBase: 'https://agent.example.com/api/v1',
    chatUploadFileConfigTemplateJson: null,
    chatUploadFileMetadataEnabled: false,
    chatUploadFileHiddenMessageTemplate: 'Uploaded {filenames}',
  },
  dispatch: jest.fn(),
};

function renderUploadHarness(strict = false) {
  const callbacks = {
    onUploadSuccess: jest.fn(),
    onUploadBatchComplete: jest.fn(),
    onUploadError: jest.fn(),
    onSendHiddenMessage: jest.fn(),
  };
  const content = (
    <HomeContext.Provider value={homeContextValue as any}>
      <ChatFileUpload
        uploadFlowSourceId="jobs-test"
        getActiveConversationId={() => 'conversation-1'}
        {...callbacks}
      >
        {({ triggerUpload }) => (
          <button type="button" onClick={triggerUpload}>Start upload</button>
        )}
      </ChatFileUpload>
    </HomeContext.Provider>
  );
  const view = render(strict ? <React.StrictMode>{content}</React.StrictMode> : content);
  return { ...view, callbacks };
}

async function startUpload() {
  fireEvent.click(screen.getByRole('button', { name: 'Start upload' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm upload' }));
  await waitFor(() => expect(mockUploadFileChunked).toHaveBeenCalledTimes(1));
}

describe('ChatFileUpload recorded video jobs', () => {
  beforeEach(() => {
    mockUploadFileChunked.mockReset();
    mockPollRecordedVideoJob.mockReset();
    mockRetryRecordedVideoJob.mockReset();
    mockCancelRecordedVideoJob.mockReset();
    mockUploadFileChunked.mockResolvedValue(acceptedUpload);
    mockRetryRecordedVideoJob.mockResolvedValue(jobStatus('queued'));
    mockCancelRecordedVideoJob.mockResolvedValue(jobStatus('cancelled'));
  });

  it('keeps callbacks blocked while processing and publishes only after completed', async () => {
    const poll = deferred<ReturnType<typeof jobStatus>>();
    mockPollRecordedVideoJob.mockReturnValue(poll.promise);
    const { callbacks } = renderUploadHarness();

    await startUpload();
    expect(await screen.findByText('Processing')).toBeInTheDocument();
    expect(callbacks.onUploadSuccess).not.toHaveBeenCalled();
    expect(callbacks.onUploadBatchComplete).not.toHaveBeenCalled();
    expect(callbacks.onSendHiddenMessage).not.toHaveBeenCalled();

    await act(async () => poll.resolve(jobStatus('completed')));
    expect(await screen.findByText('Completed')).toBeInTheDocument();
    expect(callbacks.onUploadSuccess).toHaveBeenCalledWith(acceptedUpload);
    expect(callbacks.onUploadBatchComplete).toHaveBeenCalledTimes(1);
    expect(callbacks.onSendHiddenMessage).toHaveBeenCalledWith(
      'Uploaded recorded.mp4',
      'conversation-1',
    );
  });

  it('shows a safe failure and publishes only after retry reaches completed', async () => {
    mockPollRecordedVideoJob
      .mockResolvedValueOnce(jobStatus('failed', 'Recorded video processing failed'))
      .mockResolvedValueOnce(jobStatus('completed'));
    const { callbacks } = renderUploadHarness();

    await startUpload();
    expect(await screen.findByText('Recorded video processing failed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close upload status' })).toBeInTheDocument();
    expect(callbacks.onUploadSuccess).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry recorded.mp4' }));

    await waitFor(() => expect(mockRetryRecordedVideoJob).toHaveBeenCalledWith(
      'job-1',
      expect.objectContaining({ agentApiUrl: 'https://agent.example.com/api/v1' }),
    ));
    expect(await screen.findByText('Completed')).toBeInTheDocument();
    expect(callbacks.onUploadSuccess).toHaveBeenCalledTimes(1);
  });

  it('cancels the backend job and does not publish success', async () => {
    const poll = deferred<ReturnType<typeof jobStatus>>();
    mockPollRecordedVideoJob.mockReturnValue(poll.promise);
    const { callbacks } = renderUploadHarness();

    await startUpload();
    await waitFor(() => expect(mockPollRecordedVideoJob).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel All' }));

    await waitFor(() => expect(mockCancelRecordedVideoJob).toHaveBeenCalledWith(
      'job-1',
      expect.objectContaining({ agentApiUrl: 'https://agent.example.com/api/v1' }),
    ));
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
    expect(callbacks.onUploadSuccess).not.toHaveBeenCalled();
  });

  it('sends one cancellation in Strict Mode and absorbs action failures', async () => {
    const poll = deferred<ReturnType<typeof jobStatus>>();
    mockPollRecordedVideoJob.mockReturnValue(poll.promise);
    mockCancelRecordedVideoJob.mockRejectedValue(new Error('cancel transport failed'));
    renderUploadHarness(true);

    await startUpload();
    await waitFor(() => expect(mockPollRecordedVideoJob).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel All' }));

    await waitFor(() => expect(mockCancelRecordedVideoJob).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
  });

  it('aborts an active job poll when unmounted', async () => {
    const poll = deferred<ReturnType<typeof jobStatus>>();
    mockPollRecordedVideoJob.mockReturnValue(poll.promise);
    const view = renderUploadHarness();

    await startUpload();
    await waitFor(() => expect(mockPollRecordedVideoJob).toHaveBeenCalledTimes(1));
    const signal = mockPollRecordedVideoJob.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    view.unmount();
    expect(signal.aborted).toBe(true);
  });
});
