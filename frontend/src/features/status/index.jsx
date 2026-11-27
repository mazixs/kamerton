import { useEffect, useState } from "react";
import { useConsole } from "@/app/use-console";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Button } from "@/components/ui/button";
import { detailText, formatDiskBytes } from "@/features/models/model-state";
import { estimateRtf, formatUptime, RecentFiles } from "./metrics";

function Readout({ t, items }) {
  return (
    <dl className="readout">
      {items.map(([id, label, value]) => <div key={id}><dt>{t(label)}</dt><dd id={id}>{value}</dd></div>)}
    </dl>
  );
}

function Storage({ api, active, t, lang }) {
  const [storage, setStorage] = useState(null);
  useEffect(() => {
    if (!active) return;
    let current = true;
    api("/api/storage").then(value => { if (current) setStorage(value); })
      .catch(() => { if (current) setStorage(null); });
    return () => { current = false; };
  }, [active, api]);
  const disk = storage?.models;
  const size = value => formatDiskBytes(value, t, lang);
  const estimate = value => storage?.container_root_partial && Number.isFinite(value)
    ? t("storage.minimum", { size: size(value) }) : size(value);
  const capacity = Number.isFinite(disk?.free_bytes) && Number.isFinite(disk?.total_bytes);
  const low = capacity && (disk.free_bytes < 2 * 1024 ** 3 || disk.free_bytes < 0.05 * disk.total_bytes);
  return (
    <Layout variant="panel stack" role="region" aria-labelledby="storage-title">
      <Heading level={2} id="storage-title">{t("storage.title")}</Heading>
      <Readout t={t} items={[
        ["disk-models", "storage.models", size(disk?.bytes)],
        ["disk-data", "storage.data", size(storage?.data?.bytes)],
        ["disk-root", "storage.root", estimate(storage?.container_root_bytes)],
        ["disk-total", "storage.total", estimate(storage?.container_and_volumes_bytes)],
        ["disk-free", "storage.free", capacity ? t("storage.capacity", { free: size(disk.free_bytes), total: size(disk.total_bytes) }) : t("storage.unavailable")],
      ]} />
      <p id="disk-low" className="error" hidden={!low}>{t("storage.low")}</p>
      <Paragraph variant="help">{t("storage.scope")}</Paragraph>
    </Layout>
  );
}

export function ServiceStatus({ active }) {
  const { api, status, statusError, refreshStatus, loadHeads, t, lang, mode, updateKey } = useConsole();
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState(null);
  const canStop = !!status?.engine?.running && ["ready", "error"].includes(status.status);
  const metrics = status?.metrics || {};
  const cache = status?.transcription_cache;
  const detail = status ? detailText(status, t) : statusError?.message || statusError || "—";
  const deployPercent = status?.status === "downloading" && Number.isFinite(status.download_percent)
    ? status.download_percent + "%" : "";
  const target = [status?.deploying, deployPercent].filter(Boolean).join(" · ");

  useEffect(() => { if (active) refreshStatus(); }, [active, refreshStatus]);

  async function stop() {
    if (stopping || !canStop) return;
    setStopping(true);
    setStopError(null);
    try { await api("/api/stop", { method: "POST" }); }
    catch (error) { setStopError(error); }
    finally {
      await refreshStatus();
      setStopping(false);
    }
    await loadHeads();
  }

  function editKey() {
    const entered = window.prompt(t("api.keyPrompt"), "");
    if (entered !== null) updateKey(entered.trim());
  }

  return (
    <>
      <Layout variant="panel stack">
        <Layout variant="titleline">
          <Heading level={2} id="state-detail">{detail}</Heading>
          <Button type="button" variant="outline" id="btn-stop" hidden={!canStop} disabled={!canStop || stopping} onClick={stop}>{t("btn.stop")}</Button>
        </Layout>
        <p id="stop-feedback" role="status" className="error">
          {stopError && t("status.stopFailed", { reason: stopError.status ? t("api.error", { status: stopError.status }) : t("status.stopConnection") })}
        </p>
        <Layout variant="actions" id="legacy-access" hidden={mode !== "local"}>
          <span id="key-badge" hidden={!status?.api_key_set}>{t("key.badge")}</span>
          <Button type="button" variant="outline" id="edit-key" disabled={mode !== "local"} onClick={editKey}>{t("key.edit")}</Button>
        </Layout>
        <Readout t={t} items={[
          ["ro-state", "status.readiness", status ? t("state." + status.status) : "—"],
          ["ro-target", "status.target", target || "—"],
          ["ro-variant", "ro.variant", status?.engine?.variant || "—"],
          ["ro-elapsed", "ro.elapsed", Number.isFinite(metrics.avg_elapsed) ? t("unit.seconds", { value: metrics.avg_elapsed.toFixed(2) }) : "—"],
          ["ro-rtf", "ro.rtf", estimateRtf(metrics.avg_rtf)],
          ["ro-total", "ro.total", metrics.total_files ?? "—"],
          ["ro-restarts", "ro.restarts", status?.restart_count ?? "—"],
          ["ro-uptime", "ro.uptime", formatUptime(status?.uptime_seconds, t)],
          ["ro-cache", "cache.title", cache ? t("cache.usage", { size: formatDiskBytes(cache.bytes, t, lang), hits: cache.hits, minutes: cache.ttl_seconds / 60 }) : "—"],
        ]} />
        <a className="textlink" href="#models">{t("page.models")}</a>
      </Layout>
      <Storage api={api} active={active} t={t} lang={lang} />
      <RecentFiles metrics={metrics} t={t} />
    </>
  );
}
