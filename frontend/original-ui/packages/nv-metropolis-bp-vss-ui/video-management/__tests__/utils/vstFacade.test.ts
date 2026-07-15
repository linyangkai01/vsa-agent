// SPDX-License-Identifier: MIT
import {
  SAME_ORIGIN_VST_API_URL,
  createApiEndpoints,
} from '../../lib-src/api';

describe('same-origin VST facade endpoints', () => {
  it('defaults browser requests to /api/v1/vst', () => {
    const endpoints = createApiEndpoints();

    expect(SAME_ORIGIN_VST_API_URL).toBe('/api/v1/vst');
    expect(endpoints.STREAMS).toBe('/api/v1/vst/v1/replay/streams');
    expect(endpoints.UPLOAD_FILE).toBe('/api/v1/vst/v1/storage/file');
    expect(endpoints.REPLAY_PICTURE('asset-1', '2026-07-15T01:00:00Z')).toBe(
      '/api/v1/vst/v1/replay/stream/asset-1/picture?startTime=2026-07-15T01%3A00%3A00Z',
    );
  });

  it('normalizes a configured trailing slash without creating //v1 paths', () => {
    const endpoints = createApiEndpoints('/api/v1/vst/');

    expect(endpoints.STORAGE_SIZE).toBe('/api/v1/vst/v1/storage/size?timelines=true');
  });
});
