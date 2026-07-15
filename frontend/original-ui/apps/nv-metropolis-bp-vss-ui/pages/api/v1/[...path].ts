// SPDX-License-Identifier: MIT
import { request as httpRequest } from 'http';
import { request as httpsRequest } from 'https';
import type { IncomingHttpHeaders } from 'http';
import type { NextApiRequest, NextApiResponse } from 'next';

const DEFAULT_INTERNAL_AGENT_API_URL = 'http://127.0.0.1:8000/api/v1';
const API_PREFIX = '/api/v1';
const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

export const config = {
  api: {
    bodyParser: false,
    responseLimit: false,
    externalResolver: true,
  },
};

function targetUrl(requestUrl: string | undefined, targetBase: string): URL {
  const source = requestUrl || API_PREFIX;
  if (source !== API_PREFIX && !source.startsWith(`${API_PREFIX}/`) && !source.startsWith(`${API_PREFIX}?`)) {
    throw new Error('Invalid same-origin proxy path');
  }
  const base = targetBase.replace(/\/+$/, '');
  return new URL(`${base}${source.slice(API_PREFIX.length)}`);
}

function forwardRequestHeaders(headers: IncomingHttpHeaders): IncomingHttpHeaders {
  const forwarded = { ...headers };
  for (const header of HOP_BY_HOP_HEADERS) {
    delete forwarded[header];
  }
  return forwarded;
}

function forwardResponseHeaders(response: NextApiResponse, headers: IncomingHttpHeaders): void {
  for (const [name, value] of Object.entries(headers)) {
    if (value !== undefined && !HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
      response.setHeader(name, value);
    }
  }
}

export function proxyApiRequest(
  request: NextApiRequest,
  response: NextApiResponse,
  targetBase: string,
): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    let downstreamClosed = false;
    const finish = () => {
      if (!settled) {
        settled = true;
        resolve();
      }
    };

    let target: URL;
    try {
      target = targetUrl(request.url, targetBase);
    } catch {
      response.status(400).json({ error: 'Invalid proxy request path' });
      finish();
      return;
    }

    const requestImpl = target.protocol === 'https:' ? httpsRequest : httpRequest;
    const upstreamRequest = requestImpl(
      target,
      {
        method: request.method,
        headers: forwardRequestHeaders(request.headers),
      },
      (upstreamResponse) => {
        response.statusCode = upstreamResponse.statusCode || 502;
        forwardResponseHeaders(response, upstreamResponse.headers);
        upstreamResponse.once('error', (error) => {
          if (!downstreamClosed) {
            response.destroy(error);
          }
          finish();
        });
        upstreamResponse.once('end', finish);
        upstreamResponse.pipe(response);
      },
    );

    upstreamRequest.once('error', () => {
      if (!response.headersSent) {
        response.status(502).json({ error: 'Upstream API is unavailable' });
      } else {
        response.destroy();
      }
      finish();
    });
    response.once('close', () => {
      downstreamClosed = true;
      upstreamRequest.destroy();
      finish();
    });
    request.once('aborted', () => upstreamRequest.destroy());
    request.pipe(upstreamRequest);
  });
}

export default function handler(request: NextApiRequest, response: NextApiResponse): Promise<void> {
  const targetBase = process.env.VSA_INTERNAL_AGENT_API_URL_BASE || DEFAULT_INTERNAL_AGENT_API_URL;
  return proxyApiRequest(request, response, targetBase);
}
