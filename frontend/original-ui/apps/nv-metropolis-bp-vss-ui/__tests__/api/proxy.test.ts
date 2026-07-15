// SPDX-License-Identifier: MIT
import { createServer, type Server } from 'http';
import { PassThrough } from 'stream';
import type { AddressInfo } from 'net';
import { config, proxyApiRequest } from '../../pages/api/v1/[...path]';

class CapturingResponse extends PassThrough {
  statusCode = 200;
  private readonly headers = new Map<string, string | string[]>();

  setHeader(name: string, value: string | string[]) {
    this.headers.set(name.toLowerCase(), value);
    return this;
  }

  getHeader(name: string) {
    return this.headers.get(name.toLowerCase());
  }
}

async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address() as AddressInfo;
  return `http://127.0.0.1:${address.port}/api/v1`;
}

async function close(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

function delay(ms: number): Promise<'timeout'> {
  return new Promise((resolve) => setTimeout(() => resolve('timeout'), ms));
}

function requestStream(
  method: string,
  url: string,
  headers: Record<string, string>,
): PassThrough & { method: string; url: string; headers: Record<string, string> } {
  const request = new PassThrough() as PassThrough & {
    method: string;
    url: string;
    headers: Record<string, string>;
  };
  request.method = method;
  request.url = url;
  request.headers = headers;
  Object.defineProperty(request, 'body', {
    get() {
      throw new Error('proxy must not read or serialize req.body');
    },
  });
  return request;
}

function responseBody(response: PassThrough): Promise<Buffer> {
  const chunks: Buffer[] = [];
  response.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
  return new Promise((resolve) => response.on('end', () => resolve(Buffer.concat(chunks))));
}

describe('same-origin API streaming proxy', () => {
  it('disables Next body parsing and pipes multipart bytes with nvstreamer headers', async () => {
    let receivedBody = Buffer.alloc(0);
    let receivedHeaders: typeof import('http').IncomingHttpHeaders = {};
    let receivedUrl = '';
    const upstream = createServer((request, response) => {
      const chunks: Buffer[] = [];
      receivedHeaders = request.headers;
      receivedUrl = request.url || '';
      request.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
      request.on('end', () => {
        receivedBody = Buffer.concat(chunks);
        response.writeHead(202, { 'content-type': 'application/json' });
        response.end('{"status":"accepted"}');
      });
    });
    const targetBase = await listen(upstream);
    const request = requestStream('POST', '/api/v1/vst/v1/storage/file?upload_session_id=s1', {
      host: 'localhost:3000',
      'content-type': 'multipart/form-data; boundary=test-boundary',
      'nvstreamer-chunk-number': '1',
      'nvstreamer-total-chunks': '2',
    });
    const response = new CapturingResponse();
    const bodyPromise = responseBody(response);

    try {
      const proxyPromise = proxyApiRequest(request as any, response as any, targetBase);
      request.write(Buffer.from('first-part'));
      request.end(Buffer.from('-second-part'));
      await proxyPromise;

      expect(config.api.bodyParser).toBe(false);
      expect(receivedUrl).toBe('/api/v1/vst/v1/storage/file?upload_session_id=s1');
      expect(receivedBody.toString()).toBe('first-part-second-part');
      expect(receivedHeaders['content-type']).toBe('multipart/form-data; boundary=test-boundary');
      expect(receivedHeaders['nvstreamer-chunk-number']).toBe('1');
      expect(receivedHeaders.host).toBe('localhost:3000');
      expect(response.statusCode).toBe(202);
      expect((await bodyPromise).toString()).toBe('{"status":"accepted"}');
    } finally {
      await close(upstream);
    }
  });

  it('forwards Range and streams upstream 206 headers and bytes unchanged', async () => {
    let receivedRange: string | undefined;
    const upstream = createServer((request, response) => {
      receivedRange = request.headers.range;
      response.writeHead(206, {
        'accept-ranges': 'bytes',
        'content-range': 'bytes 2-4/10',
        'content-length': '3',
        'content-type': 'video/mp4',
      });
      response.write(Buffer.from([2, 3]));
      response.end(Buffer.from([4]));
    });
    const targetBase = await listen(upstream);
    const request = requestStream('GET', '/api/v1/vst/v1/storage/file/asset-1', {
      host: 'localhost:3000',
      range: 'bytes=2-4',
    });
    const response = new CapturingResponse();
    const bodyPromise = responseBody(response);

    try {
      request.end();
      await proxyApiRequest(request as any, response as any, targetBase);

      expect(receivedRange).toBe('bytes=2-4');
      expect(response.statusCode).toBe(206);
      expect(response.getHeader('accept-ranges')).toBe('bytes');
      expect(response.getHeader('content-range')).toBe('bytes 2-4/10');
      expect([...await bodyPromise]).toEqual([2, 3, 4]);
    } finally {
      await close(upstream);
    }
  });

  it('streams search-result thumbnails through the same-origin video route', async () => {
    let receivedUrl = '';
    const upstream = createServer((request, response) => {
      receivedUrl = request.url || '';
      response.writeHead(200, { 'content-type': 'image/jpeg' });
      response.end(Buffer.from([0xff, 0xd8, 0xff, 0xd9]));
    });
    const targetBase = await listen(upstream);
    const request = requestStream(
      'GET',
      '/api/v1/videos/asset-1/segments/segment-1/thumbnail',
      { host: 'localhost:3000' },
    );
    const response = new CapturingResponse();
    const bodyPromise = responseBody(response);

    try {
      request.end();
      await proxyApiRequest(request as any, response as any, targetBase);

      expect(receivedUrl).toBe('/api/v1/videos/asset-1/segments/segment-1/thumbnail');
      expect(response.getHeader('content-type')).toBe('image/jpeg');
      expect([...await bodyPromise]).toEqual([0xff, 0xd8, 0xff, 0xd9]);
    } finally {
      await close(upstream);
    }
  });

  it('cancels the upstream stream when the browser connection closes', async () => {
    let resolveUpstreamClosed: () => void = () => undefined;
    const upstreamClosed = new Promise<void>((resolve) => {
      resolveUpstreamClosed = resolve;
    });
    const upstream = createServer((_request, response) => {
      response.once('close', resolveUpstreamClosed);
      response.writeHead(200, { 'content-type': 'video/mp4' });
      response.write(Buffer.from([1, 2, 3]));
    });
    const targetBase = await listen(upstream);
    const request = requestStream('GET', '/api/v1/vst/v1/storage/file/asset-1', {
      host: 'localhost:3000',
    });
    const response = new CapturingResponse();
    const firstChunk = new Promise<void>((resolve) => response.once('data', () => resolve()));

    try {
      const proxyPromise = proxyApiRequest(request as any, response as any, targetBase);
      request.end();
      await firstChunk;
      response.emit('close');

      expect(await Promise.race([proxyPromise.then(() => 'settled' as const), delay(100)])).toBe('settled');
      await upstreamClosed;
    } finally {
      upstream.closeAllConnections();
      await close(upstream);
    }
  });
});
