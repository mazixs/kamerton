import { HISTORY_KEY, historyRetention } from "@/lib/history-retention";
const MAX_ENTRIES = 200;
const MAX_JSON_LENGTH = 1_500_000;

export function transcriptSegments(result) {
  if (!Array.isArray(result?.segments)) return [];
  return result.segments.filter((segment) =>
    Number.isFinite(segment?.start) && segment.start >= 0 &&
    typeof segment.speaker === "string" && typeof segment.text === "string"
  );
}

export function readHistory() {
  const retention = historyRetention();
  if (retention === "off") {
    localStorage.removeItem(HISTORY_KEY);
    return [];
  }
  const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  const cutoff = retention === "forever" ? 0 : Date.now() - Number(retention) * 86_400_000;
  const entries = Array.isArray(saved) ? saved.filter((entry) =>
    typeof entry?.id === "string" && /^[a-z\d-]{1,80}$/i.test(entry.id) &&
    typeof entry.filename === "string" && Number.isFinite(entry.at) &&
    entry.at >= cutoff && entry.at <= 8.64e15 && typeof entry.result?.text === "string"
  ).slice(0, MAX_ENTRIES) : [];
  if (entries.length !== saved?.length) localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
  return entries;
}

export function saveHistory(filename, result) {
  const entries = readHistory();
  if (historyRetention() === "off") return entries;
  const at = Date.now();
  const id = window.crypto?.randomUUID?.() || `${at}-${Math.random().toString(36).slice(2)}`;
  const entry = { id, at, filename, result: { text: result.text || "", segments: transcriptSegments(result) } };
  if (!entry.result.text.trim() && !entry.result.segments.length) return entries;
  const serialized = [JSON.stringify(entry)];
  let length = serialized[0].length + 2;
  if (length > MAX_JSON_LENGTH) throw new Error("Transcript exceeds history capacity");
  const next = [entry];
  for (const previous of entries.slice(0, MAX_ENTRIES - 1)) {
    const text = JSON.stringify(previous);
    if (length + text.length + 1 > MAX_JSON_LENGTH) break;
    next.push(previous);
    serialized.push(text);
    length += text.length + 1;
  }
  localStorage.setItem(HISTORY_KEY, `[${serialized.join(",")}]`);
  return next;
}

export function speakerLabel(segment, t) {
  const offset = Math.floor(segment.start);
  const time = `${Math.floor(offset / 60)}:${String(offset % 60).padStart(2, "0")}`;
  const speaker = segment.speaker === "unknown" ? t("diarization.unknown") :
    t("diarization.speaker", { number:segment.speaker.replace("speaker_", "") });
  return `${time} · ${speaker}`;
}

export function transcriptText(result, t) {
  const segments = transcriptSegments(result);
  if (!segments.length) return result?.text || "";
  return segments.map((segment) => `${speakerLabel(segment, t)}\n${segment.text}`).join("\n");
}
