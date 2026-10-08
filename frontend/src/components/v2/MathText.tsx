import { useMemo } from 'react';
import 'katex/dist/katex.min.css';
import { render } from './math';

/**
 * Renders exam text with inline `$...$` and display `$$...$$` LaTeX via KaTeX.
 * Anything KaTeX cannot parse is shown as the raw source instead of breaking the line.
 */
export default function MathText({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => render(text), [text]);
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
