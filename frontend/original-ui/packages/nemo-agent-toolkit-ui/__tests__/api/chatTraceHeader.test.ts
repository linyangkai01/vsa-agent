import handler from '../../pages/api/chat';

describe('Chat API proxy trace header', () => {
  it('forwards the upstream X-VSA-Trace-ID header to the browser response', async () => {
    const fetchMock = jest.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          choices: [{ message: { content: 'Forklift response' } }],
        }),
        {
          status: 200,
          headers: { 'X-VSA-Trace-ID': 'trace-20260729-abc123' },
        },
      ),
    );
    const request = new Request('http://localhost/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Conversation-Id': 'conversation-1',
        'User-Message-ID': 'message-1',
      },
      body: JSON.stringify({
        chatCompletionURL: 'http://agent.example/api/chat',
        messages: [{ role: 'user', content: 'Describe the selected video.' }],
      }),
    });

    const response = await handler(request);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(response.status).toBe(200);
    expect(response.headers.get('x-vsa-trace-id')).toBe(
      'trace-20260729-abc123',
    );
    await expect(response.text()).resolves.toBe('Forklift response');
  });
});
