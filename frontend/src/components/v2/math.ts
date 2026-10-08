import katex from 'katex';

/** Display-mode LaTeX (a slide's formula); falls back to the raw source. */
export function renderDisplay(tex: string): string {
  try {
    return katex.renderToString(tex.replace(/^\$+|\$+$/g, ''), { displayMode: true, throwOnError: true, strict: 'ignore', output: 'html' });
  } catch {
    return `<code>${escapeHtml(tex)}</code>`;
  }
}

export function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function render(text: string): string {
  const out: string[] = [];
  const re = /\$\$([\s\S]+?)\$\$|\$([^$]+?)\$/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    out.push(escapeHtml(text.slice(last, m.index)));
    const tex = (m[1] ?? m[2]).trim();
    try {
      out.push(katex.renderToString(tex, { displayMode: false, throwOnError: true, strict: 'ignore', output: 'html' }));
    } catch {
      out.push(`<code>${escapeHtml(m[0])}</code>`);
    }
    last = re.lastIndex;
  }
  out.push(escapeHtml(text.slice(last)));
  return out.join('');
}
