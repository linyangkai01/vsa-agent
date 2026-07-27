import { render, screen } from '@testing-library/react';
import React from 'react';

import { getReactMarkDownCustomComponents } from '@/components/Markdown/CustomComponents';

jest.mock('@/components/Markdown/CodeBlock', () => ({
  CodeBlock: ({ value }: { value: string }) => (
    <div className="codeblock">
      <pre>{value}</pre>
    </div>
  ),
}));

jest.mock('next-i18next', () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}));

describe('Markdown custom components', () => {
  it('renders inline code as phrasing content inside a paragraph', () => {
    const consoleError = jest
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    const CodeRenderer = getReactMarkDownCustomComponents()
      .code as React.ElementType;

    const { container } = render(
      <p>
        Use <CodeRenderer>model-name</CodeRenderer> for this request.
      </p>,
    );

    expect(screen.getByText('model-name').tagName).toBe('CODE');
    expect(container.querySelector('.codeblock')).not.toBeInTheDocument();
    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
