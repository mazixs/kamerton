import { useEffect, useRef, useState } from "react";

const SERVER_STAGES = new Set([
  "queued", "decoding", "recognizing", "recognizing_speakers", "diarizing", "cache_hit", "preparing_result",
]);
const INITIAL_RESULT = { result: null, error: null, message: "audio.empty", stage: null };

export function useTranscription({ api, status, subscribe, refreshStatus, onResult }) {
  const [view, setView] = useState(INITIAL_RESULT);
  const request = useRef(null);

  useEffect(() => subscribe((event) => {
    const current = request.current;
    if (event.type === "transcription" && current?.id && event.id === current.id && SERVER_STAGES.has(event.stage)) {
      setView((previous) => ({ ...previous, stage: event.stage }));
    }
  }), [subscribe]);

  useEffect(() => {
    const abortUpload = () => {
      request.current?.controller.abort();
      request.current = null;
    };
    const onPageHide = () => {
      if (!request.current) return;
      abortUpload();
      setView(INITIAL_RESULT);
    };
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      abortUpload();
    };
  }, []);

  function reset(message = "audio.empty") {
    request.current?.controller.abort();
    request.current = null;
    setView({ ...INITIAL_RESULT, message });
  }

  async function submit(blob, filename, { source = "file", diarize = false } = {}) {
    if (!blob || request.current || status?.status !== "ready") return;
    const controller = new AbortController();
    const id = window.crypto?.randomUUID?.();
    const active = { controller, id };
    request.current = active;
    const form = new FormData();
    form.append("file", blob, filename);
    form.append("source", source);
    if (id) form.append("progress_id", id);
    const install = diarize && !status.diarization_installed;
    setView({ ...INITIAL_RESULT, stage: install ? "diarization_download" : "upload" });
    try {
      if (install) {
        await api("/api/models/diarization", { method: "POST", signal: controller.signal });
        if (request.current !== active) return;
        setView({ ...INITIAL_RESULT, stage: "upload" });
      }
      if (diarize) form.append("response_format", "diarized_json");
      const result = await api("/api/test", { method: "POST", body: form, signal: controller.signal });
      if (request.current === active) {
        setView({ ...INITIAL_RESULT, result });
        onResult(filename, result);
      }
    } catch (error) {
      if (request.current === active) setView({ ...INITIAL_RESULT, error });
    } finally {
      if (request.current === active) {
        request.current = null;
        void refreshStatus();
      }
    }
  }

  return { ...view, submit, reset };
}
