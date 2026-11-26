(() => {
  const maxFileBytes = 512 * 1024;
  const generic = new Set('the and for file files find code where this that look search project repository implementation how please'.split(' '));
  const ignored = new Set(['.git', '.svn', 'node_modules', 'dist', 'build', 'bin', 'obj', '.venv', '__pycache__']);

  function keywords(text) {
    return [...new Set((text.toLowerCase().match(/[\p{L}\p{N}_-]{2,}/gu) || []).filter(term => !generic.has(term)))].slice(0, 12);
  }

  function score(text, terms) {
    const lower = text.toLowerCase();
    return terms.reduce((total, term) => total + Number(lower.includes(term)), 0);
  }

  function excerpt(file, terms, requireMatch) {
    const lines = file.text.split(/\r?\n/);
    const nameScore = score(file.name, terms);
    let bestScore = 0;
    let bestLine = 0;
    for (let line = 0; line < lines.length; line++) {
      const value = score(lines[line], terms);
      if (value > bestScore) {
        bestScore = value;
        bestLine = line;
      }
    }
    if (requireMatch && !(bestScore || nameScore)) return null;
    let start = Math.max(0, bestLine - 4);
    while (start < bestLine && lines.slice(start, bestLine).join('\n').length > 350) start++;
    const focused = lines[bestLine];
    const column = focused.length > 1100
      ? terms.map(term => focused.toLowerCase().indexOf(term)).find(index => index >= 0) ?? 0
      : 0;
    const text = focused.length > 1100
      ? focused.slice(Math.max(0, column - 300), Math.max(0, column - 300) + 1100)
      : lines.slice(start, bestLine + 13).join('\n').slice(0, 1500);
    return {name: file.name, line: (focused.length > 1100 ? bestLine : start) + 1,
      text, rank: bestScore * 3 + nameScore * 2};
  }

  async function read(file, name = file.name) {
    if (!file.size || file.size > maxFileBytes) throw new Error('Choose a text file up to 512 KiB.');
    const bytes = new Uint8Array(await file.arrayBuffer());
    const encoding = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le'
      : bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : 'utf-8';
    let text;
    try { text = new TextDecoder(encoding, {fatal: true}).decode(bytes); }
    catch { throw new Error('Choose a UTF-8 or UTF-16 text file.'); }
    if (!text.trim() || text.includes('\0')) throw new Error('Choose a non-empty text or source file.');
    return {name: name.slice(-260), text};
  }

  function fromAttachments(files, prompt) {
    const terms = keywords(prompt);
    const limit = files.length ? Math.floor(6 / files.length) : 0;
    return files.flatMap(file => {
      if (file.text.length <= 1500) return [{name: file.name, line: 1, text: file.text}];
      const chunks = [];
      let line = 1;
      let cursor = 0;
      while (cursor < file.text.length) {
        let end = Math.min(cursor + 1500, file.text.length);
        const boundary = file.text.lastIndexOf('\n', end - 1);
        if (end < file.text.length && boundary >= cursor + 500) end = boundary + 1;
        const text = file.text.slice(cursor, end);
        chunks.push({name: file.name, line, text, score: score(text, terms)});
        line += (text.match(/\n/g) || []).length;
        cursor = end;
      }
      return chunks.sort((a, b) => b.score - a.score).slice(0, limit);
    });
  }

  async function fromFolder(files, query) {
    const terms = keywords(query);
    const candidates = [...files].filter(file => {
      const parts = (file.webkitRelativePath || file.name).split('/').slice(1);
      return file.size > 0 && file.size <= maxFileBytes && !parts.some(part => ignored.has(part.toLowerCase()))
        && !/^(?:\.env(?:\.|$)|id_(?:rsa|ed25519)$)|\.(?:pem|key|pfx)$/i.test(file.name);
    }).sort((a, b) => score(b.webkitRelativePath || b.name, terms) - score(a.webkitRelativePath || a.name, terms));
    const matches = [];
    let readBytes = 0;
    let scanned = 0;
    for (const file of candidates) {
      if (scanned >= 2400 || readBytes + file.size > 24 * 1024 * 1024) break;
      scanned++;
      readBytes += file.size;
      try {
        const hit = excerpt(await read(file, file.webkitRelativePath || file.name), terms, true);
        if (hit?.text) matches.push(hit);
      } catch {}
    }
    matches.sort((a, b) => b.rank - a.rank);
    return {excerpts: matches.slice(0, 3), scanned, capped: scanned < candidates.length};
  }

  window.localFiles = {read, fromAttachments, fromFolder};
})();
