export function deployBusy(status) {
  const name = typeof status === "string" ? status : status?.status;
  return name === "downloading" || name === "starting";
}

export function downloadReason(params, t) {
  const status = params.http_status;
  if (Number.isInteger(status) && status >= 400 && status <= 599) {
    const key = [401, 403, 429].includes(status) ? status : status >= 500 ? "server" : "other";
    return t("download.http." + key, { status });
  }
  const key = "download." + params.kind;
  const reason = t(key);
  return reason === key ? t("download.other") : reason;
}

export function startupReason(params, t) {
  const key = "models.start." + params.start_kind;
  const reason = t(key);
  return reason === key ? t("models.start.other") : reason;
}

export function detailText(status, t) {
  const code = status?.detail_code;
  if (!code) return status?.detail || "—";
  const params = { ...status.detail_params };
  if (params.kind) params.reason = downloadReason(params, t);
  if (params.start_kind) params.reason = startupReason(params, t);
  const key = "detail." + code;
  let message = t(key, params);
  if (message === key) return status.detail || "—";
  if (code === "download.failed") {
    if (params.attempts > 1) message += t("detail.download.failedAttempts", params);
    if (params.running) message += t("detail.download.failedRunning", params);
  }
  return message;
}

export function modelFailure(id, status, t) {
  const params = status?.detail_params || {};
  const code = status?.detail_code;
  if (code === "download.failed" && params.variant === id) return downloadReason(params, t);
  if (code === "deploy.runtime_unavailable" && params.variant === id) return t("detail." + code, params);
  if ((code === "start.failed" && params.variant === id) ||
      (["rollback.starting", "rollback.done", "rollback.failed"].includes(code) && params.failed === id)) {
    return startupReason(params, t);
  }
  return "";
}

export function formatDiskBytes(bytes, t, lang) {
  if (!Number.isFinite(bytes)) return t("storage.unavailable");
  const units = ["storage.b", "storage.kib", "storage.mib", "storage.gib", "storage.tib"];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) {
    bytes /= 1024;
    index += 1;
  }
  const value = new Intl.NumberFormat(lang, { maximumFractionDigits: index < 2 ? 0 : 1 }).format(bytes);
  return value + "\u00a0" + t(units[index]);
}
