// Учитываем слова, пробелы и знаки препинания. Размер матрицы ограничен,
// поэтому длинные записи сравниваются и без подсветки отдельных слов.
export function diffTokens(textA, textB) {
  const tokens = (text) => text.match(/[\p{L}\p{M}\p{N}]+|\s+|[^\s\p{L}\p{M}\p{N}]/gu) || [];
  const a = tokens(textA);
  const b = tokens(textB);
  const n = a.length;
  const m = b.length;
  let start = 0;
  let end = 0;
  while (start < n && start < m && a[start] === b[start]) start++;
  while (end < n - start && end < m - start && a[n - 1 - end] === b[m - 1 - end]) end++;
  const rows = n - start;
  const cols = m - start;
  if ((rows + 1) * (cols + 1) > 1_000_000) return null;
  const sameA = new Uint8Array(n);
  const sameB = new Uint8Array(m);
  for (const flags of [sameA, sameB]) {
    flags.fill(1, 0, start);
    flags.fill(1, flags.length - end);
  }
  const stride = cols + 1;
  const grid = new Uint32Array((rows + 1) * stride);
  for (let i = rows - 1; i >= 0; i--) {
    for (let j = cols - 1; j >= 0; j--) {
      const position = i * stride + j;
      grid[position] = a[start + i] === b[start + j]
        ? 1 + grid[position + stride + 1]
        : Math.max(grid[position + stride], grid[position + 1]);
    }
  }
  let i = 0;
  let j = 0;
  while (i < rows && j < cols) {
    if (a[start + i] === b[start + j]) {
      sameA[start + i++] = 1;
      sameB[start + j++] = 1;
    } else if (grid[(i + 1) * stride + j] >= grid[i * stride + j + 1]) i++;
    else j++;
  }
  return [groupTokens(a, sameA), groupTokens(b, sameB)];
}

function groupTokens(tokens, flags) {
  const groups = [];
  for (let start = 0; start < tokens.length;) {
    let end = start + 1;
    while (end < tokens.length && flags[start] === flags[end]) end++;
    groups.push({ text: tokens.slice(start, end).join(""), changed: flags[start] === 0 });
    start = end;
  }
  return groups;
}
