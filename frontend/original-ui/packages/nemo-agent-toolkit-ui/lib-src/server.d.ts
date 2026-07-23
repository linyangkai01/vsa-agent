// SPDX-License-Identifier: MIT

import type { GetServerSidePropsContext, NextApiHandler } from 'next';

export interface ApiWrapperOptions {
  allowedMethods?: string[];
  bodyParserConfig?: {
    sizeLimit?: string;
  };
}

export declare function getNemoAgentToolkitSSProps(
  context: GetServerSidePropsContext,
): Promise<{ props: Record<string, unknown> }>;

export declare function createApiWrapper(
  edgeHandler: (request: Request) => Promise<Response>,
  options?: ApiWrapperOptions,
): NextApiHandler;

export declare function createChatApiWrapper(
  edgeHandler: (request: Request) => Promise<Response>,
): NextApiHandler;

export declare const chatApiHandler: NextApiHandler;
