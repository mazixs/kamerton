export const HISTORY_KEY = "kamerton_dictation_history";
export const RETENTION_KEY = "kamerton_history_retention";
export const RETENTION_EVENT = "kamerton:history-retention";
export const RETENTION_VALUES = ["off", "7", "30", "90", "forever"];

export function historyRetention() {
  try {
    const value = localStorage.getItem(RETENTION_KEY);
    if (RETENTION_VALUES.includes(value)) return value;
  } catch {
    // Режим хранения по умолчанию при недоступном хранилище.
  }
  return "30";
}

export function setHistoryRetention(value) {
  if (!RETENTION_VALUES.includes(value)) return;
  localStorage.setItem(RETENTION_KEY, value);
  if (value === "off") localStorage.removeItem(HISTORY_KEY);
  window.dispatchEvent(new Event(RETENTION_EVENT));
}
