export function fold(phrase) {
  return phrase.toLowerCase().replace(/\u0451/g, "е");
}

export function parseGlossary(text = "") {
  return text.split(/[\n,]/).map((chunk) => {
    const [phrase, weight = ""] = chunk.split("|").map((part) => part.trim());
    return { phrase, weight };
  }).filter(({ phrase }) => phrase);
}

export function entryText(entries) {
  return entries.map(({ phrase, weight }) => weight ? phrase + "|" + weight : phrase).join("\n");
}

export function mergePhrases(entries, text) {
  const indices = new Map();
  entries.forEach(({ phrase }, index) => {
    const key = fold(phrase);
    if (!indices.has(key)) indices.set(key, index);
  });
  const merged = [...entries];
  const incoming = parseGlossary(text);
  let duplicate = null;
  for (const entry of incoming) {
    const key = fold(entry.phrase);
    if (indices.has(key)) {
      duplicate = indices.get(key);
    } else {
      indices.set(key, merged.length);
      merged.push(entry);
    }
  }
  const added = merged.length - entries.length;
  return { entries: merged, added, duplicate, skipped: incoming.length - added };
}

export function groupIssues(issues = []) {
  const grouped = new Map();
  for (const { code, phrase } of issues) {
    if (!grouped.has(code)) grouped.set(code, []);
    grouped.get(code).push(phrase);
  }
  return grouped;
}
