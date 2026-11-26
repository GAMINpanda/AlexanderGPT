(() => {
  const delimiters = [
    ['$$', '$$', true],
    ['\\[', '\\]', true],
    ['\\(', '\\)', false],
    ...['equation', 'align', 'alignat', 'gather'].map(name => [
      '\\begin{' + name + '}', '\\end{' + name + '}', true, true,
    ]),
    ['$', '$', false],
  ];
  let markdown;

  function tokenizeMath(state, silent) {
    const source = state.src;
    const start = state.pos;
    const delimiter = delimiters.find(([open]) => source.startsWith(open, start));
    if (!delimiter) return false;
    const [open, close, display, environment] = delimiter;
    const contentStart = start + open.length;
    if (open === '$' && /\s/.test(source[contentStart] || ' ')) return false;
    let end = source.indexOf(close, contentStart);
    while (end !== -1) {
      let backslashes = 0;
      while (source[end - 1 - backslashes] === '\\') backslashes++;
      if (backslashes % 2 === 0) break;
      end = source.indexOf(close, end + close.length);
    }
    if (end <= contentStart || end + close.length > state.posMax) return false;
    if (open === '$' && (/\s/.test(source[end - 1]) || /\d/.test(source[end + 1] || ''))) return false;
    if (!silent) {
      const token = state.push('local_math', '', 0);
      token.markup = source.slice(start, end + close.length);
      token.content = environment ? token.markup : source.slice(contentStart, end);
      token.meta = {display};
    }
    state.pos = end + close.length;
    return true;
  }

  function getRenderer() {
    if (markdown || typeof window.markdownit !== 'function') return markdown;
    markdown = window.markdownit({html: false, linkify: true});
    markdown.inline.ruler.before('escape', 'local_math', tokenizeMath);
    markdown.renderer.rules.local_math = (tokens, index) => {
      const token = tokens[index];
      try {
        return window.katex.renderToString(token.content, {
          displayMode: token.meta.display, trust: false, throwOnError: true,
        });
      } catch {
        return markdown.utils.escapeHtml(token.markup);
      }
    };
    markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
      tokens[index].attrSet('target', '_blank');
      tokens[index].attrSet('rel', 'noopener noreferrer');
      return renderer.renderToken(tokens, index, options);
    };
    markdown.renderer.rules.image = (tokens, index, options, env, renderer) => {
      const token = tokens[index];
      const label = markdown.utils.escapeHtml(renderer.renderInlineAsText(token.children, options, env) || 'Image');
      const source = token.attrGet('src');
      return /^https?:\/\//i.test(source)
        ? '<a target="_blank" rel="noopener noreferrer" href="' + markdown.utils.escapeHtml(source) + '">' + label + '</a>'
        : label;
    };
    return markdown;
  }

  window.renderReplyMarkdown = (element, text) => {
    const renderer = getRenderer();
    element.classList.toggle('markdown', Boolean(renderer));
    if (renderer) element.innerHTML = renderer.render(text);
    else element.textContent = text;
  };
})();
