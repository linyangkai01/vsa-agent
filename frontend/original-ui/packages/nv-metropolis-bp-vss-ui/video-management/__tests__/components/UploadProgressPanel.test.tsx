// SPDX-License-Identifier: MIT
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { UploadProgressPanel } from '../../lib-src/components/UploadProgressPanel';
import type { UploadProgress } from '../../lib-src/types';

const noop = () => {};

function uploadList(overrides: Partial<UploadProgress>[]): UploadProgress[] {
  return overrides.map((u, i) => ({
    id: u.id ?? `id-${i}`,
    fileName: u.fileName ?? `file-${i}.mp4`,
    progress: u.progress ?? 0,
    status: u.status ?? 'pending',
    error: u.error,
    assetId: u.assetId,
    jobId: u.jobId,
    statusUrl: u.statusUrl,
  }));
}

describe('UploadProgressPanel', () => {
  it('shows processing header when uploads are only in processing state', () => {
    render(
      <UploadProgressPanel
        uploads={uploadList([{ status: 'processing', fileName: 'a.mp4', progress: 100 }])}
        onClose={noop}
        onCancel={noop}
      />,
    );

    expect(screen.getByText('Processing 1 file...')).toBeInTheDocument();
  });

  it('pluralizes processing header for multiple processing uploads', () => {
    render(
      <UploadProgressPanel
        uploads={uploadList([
          { status: 'processing', fileName: 'a.mp4', progress: 100 },
          { status: 'processing', fileName: 'b.mp4', progress: 100 },
        ])}
        onClose={noop}
        onCancel={noop}
      />,
    );

    expect(screen.getByText('Processing 2 files...')).toBeInTheDocument();
  });

  it('shows per-row Processing label for processing status', () => {
    render(
      <UploadProgressPanel
        uploads={uploadList([{ status: 'processing', fileName: 'job.mp4', progress: 100 }])}
        onClose={noop}
        onCancel={noop}
      />,
    );

    expect(screen.getByText('Processing...')).toBeInTheDocument();
    expect(screen.getByText('job.mp4')).toBeInTheDocument();
  });

  it('prefers uploading header when both uploading and processing are present', () => {
    render(
      <UploadProgressPanel
        uploads={uploadList([
          { status: 'uploading', fileName: 'up.mp4', progress: 50 },
          { status: 'processing', fileName: 'done.mp4', progress: 100 },
        ])}
        onClose={noop}
        onCancel={noop}
      />,
    );

    expect(screen.queryByText(/Processing \d+ file/)).not.toBeInTheDocument();
    // Count includes both uploading and processing so the display only ever
    // grows as files advance (uploading → processing → success).
    expect(screen.getByText('Uploading 2/2 files...')).toBeInTheDocument();
  });

  it('shows an explicit Completed label for a successful job', () => {
    render(
      <UploadProgressPanel
        uploads={uploadList([{ status: 'success', fileName: 'done.mp4', progress: 100 }])}
        onClose={noop}
        onCancel={noop}
      />,
    );

    expect(screen.getByText('Completed')).toBeInTheDocument();
  });

  it('shows the safe error and retries the selected failed job', () => {
    const onRetry = jest.fn();
    const failed = uploadList([{
      id: 'failed-1',
      jobId: 'job-1',
      status: 'error',
      fileName: 'failed.mp4',
      error: 'Recorded video processing failed',
    }]);

    render(
      <UploadProgressPanel
        uploads={failed}
        onClose={noop}
        onCancel={noop}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText('Recorded video processing failed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry failed.mp4' }));
    expect(onRetry).toHaveBeenCalledWith(failed[0]);
  });

  it('shows an explicit Cancelled label for a cancelled job', () => {
    render(
      <UploadProgressPanel
        uploads={uploadList([{ status: 'cancelled', fileName: 'cancelled.mp4' }])}
        onClose={noop}
        onCancel={noop}
      />,
    );

    expect(screen.getByText('Cancelled')).toBeInTheDocument();
  });
});
