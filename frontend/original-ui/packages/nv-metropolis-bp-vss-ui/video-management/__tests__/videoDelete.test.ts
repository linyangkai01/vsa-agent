import { deleteVideo } from '../lib-src/videoDelete';

const response = (status: number, body = ''): Response =>
  new Response(body || null, {
    status,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
  });

describe('deleteVideo', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('accepts an empty 204 completed response', async () => {
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValue(response(204));

    await expect(deleteVideo('http://agent/api/v1', 'video-1')).resolves.toEqual({
      status: 'completed',
      message: '',
      video_id: 'video-1',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('polls DELETE after 202 until the backend returns 204', async () => {
    const fetchMock = jest
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        response(
          202,
          JSON.stringify({ status: 'pending', pending: true, retry_after_ms: 10, asset_id: 'video-1' })
        )
      )
      .mockResolvedValueOnce(response(204));

    const deletion = deleteVideo('http://agent/api/v1', 'video-1');
    await jest.advanceTimersByTimeAsync(10);

    await expect(deletion).resolves.toMatchObject({ status: 'completed', video_id: 'video-1' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('polls a legacy 200 pending response instead of reporting success', async () => {
    const fetchMock = jest
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        response(
          200,
          JSON.stringify({ status: 'pending', pending: true, retry_after_ms: 10, video_id: 'video-1' })
        )
      )
      .mockResolvedValueOnce(response(204));

    const deletion = deleteVideo('http://agent/api/v1', 'video-1');
    await jest.advanceTimersByTimeAsync(10);

    await expect(deletion).resolves.toMatchObject({ status: 'completed', video_id: 'video-1' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('rejects an unknown successful response instead of reporting completion', async () => {
    jest
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(response(200, JSON.stringify({ status: 'accepted', video_id: 'video-1' })));

    await expect(deleteVideo('http://agent/api/v1', 'video-1')).rejects.toThrow(
      'Delete video returned an unexpected success response'
    );
  });

  it('rejects clearly when deletion stays pending beyond the bounded attempts', async () => {
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      response(
        202,
        JSON.stringify({ status: 'pending', pending: true, retry_after_ms: 1, asset_id: 'video-1' })
      )
    );

    const deletion = deleteVideo('http://agent/api/v1', 'video-1');
    const expectation = expect(deletion).rejects.toThrow(
      'Timed out waiting for video deletion to complete'
    );
    await jest.runAllTimersAsync();

    await expectation;
    expect(fetchMock).toHaveBeenCalledTimes(20);
  });
});
