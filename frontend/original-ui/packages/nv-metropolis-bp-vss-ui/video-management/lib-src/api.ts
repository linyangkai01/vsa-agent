// SPDX-License-Identifier: MIT
export const SAME_ORIGIN_VST_API_URL = '/api/v1/vst';

const stripTrailingSlashes = (value: string): string => value.replace(/\/+$/, '');

export const createApiEndpoints = (vstApiUrl = SAME_ORIGIN_VST_API_URL) => {
  const baseUrl = stripTrailingSlashes(vstApiUrl) || SAME_ORIGIN_VST_API_URL;
  return {
    STREAMS: `${baseUrl}/v1/replay/streams`,
    ADD_SENSOR: `${baseUrl}/v1/sensor/add`,
    DELETE_SENSOR: (sensorId: string) => `${baseUrl}/v1/sensor/${sensorId}`,
    DELETE_STORAGE_FILES: (sensorId: string, startTime: string, endTime: string) =>
      `${baseUrl}/v1/storage/file/${sensorId}?startTime=${encodeURIComponent(startTime)}&endTime=${encodeURIComponent(endTime)}`,
    LIVE_PICTURE: (streamId: string) => `${baseUrl}/v1/live/stream/${streamId}/picture`,
    REPLAY_PICTURE: (streamId: string, startTime: string) =>
      `${baseUrl}/v1/replay/stream/${streamId}/picture?startTime=${encodeURIComponent(startTime)}`,
    STORAGE_SIZE: `${baseUrl}/v1/storage/size?timelines=true`,
    UPLOAD_FILE: `${baseUrl}/v1/storage/file`,
  } as const;
};

