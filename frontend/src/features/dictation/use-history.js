import { useCallback, useEffect, useState } from "react";
import { HISTORY_KEY, RETENTION_KEY, RETENTION_EVENT, historyRetention } from "@/lib/history-retention";
import { readHistory, saveHistory } from "./history.js";

export function useHistory(active) {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(false);
  const [retention, setRetention] = useState(historyRetention);

  const refresh = useCallback(() => {
    setRetention(historyRetention());
    try {
      setEntries(readHistory());
      setError(false);
    } catch {
      setEntries([]);
      setError(true);
    }
  }, []);

  useEffect(() => {
    if (active) refresh();
    const onVisibility = () => { if (active && !document.hidden) refresh(); };
    const onStorage = (event) => {
      if (event.key === null || [HISTORY_KEY, RETENTION_KEY].includes(event.key)) refresh();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(RETENTION_EVENT, refresh);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(RETENTION_EVENT, refresh);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active, refresh]);

  function save(filename, result) {
    try {
      setEntries(saveHistory(filename, result));
      setRetention(historyRetention());
      setError(false);
      return true;
    } catch {
      setError(true);
      return false;
    }
  }

  return { entries, error, retention, save };
}
