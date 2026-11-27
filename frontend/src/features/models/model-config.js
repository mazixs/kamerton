export function modelProfile(status, id) {
  if (!status?.defaults || !id) return {};
  if (status.defaults.variant === id) return status.defaults;
  return status.model_configs?.[id] || status.env?.config || status.defaults;
}

export function modelDraft(head, config, hasGlossary) {
  const variant = head.id;
  const threads = config.alternate_threads === "" || config.alternate_threads == null
    ? null : Number(config.alternate_threads);
  if (head.runtime === "whisper") {
    return { variant, alternate_threads: threads, whisper_beam_size: Number(config.whisper_beam_size ?? 5) };
  }
  if (head.runtime === "sherpa") {
    return { variant, alternate_threads: threads, punctuation: config.punctuation === "off" ? "off" : "on" };
  }
  if (head.runtime === "gigaam_v4") return { variant, alternate_threads: threads };
  if (variant === "nemotron_35_asr") return { variant, nemotron_language: config.nemotron_language || "auto" };
  if (head.runtime === "parakeet") return { variant, parakeet_max_segment: Number(config.parakeet_max_segment ?? 30) };

  const pool = Number(config.pool_size ?? 1);
  return {
    variant,
    punctuation: config.punctuation || "auto",
    itn: config.itn || "auto",
    vad: Boolean(config.vad),
    pool_size: pool,
    file_window_concurrency: Math.min(pool, Number(config.file_window_concurrency ?? 1)),
    ...((hasGlossary || config.hotwords_default) && { hotwords_boost: Number(config.hotwords_boost ?? 1) }),
    hotwords_default: Boolean(config.hotwords_default),
  };
}

export function envWindowConflict(config) {
  return Boolean(config && config.file_window_concurrency > config.pool_size);
}
