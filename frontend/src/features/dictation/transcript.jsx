import { Layout, Paragraph } from "@/components/native/layout";
import { speakerLabel, transcriptSegments } from "./history.js";

export function Transcript({ result, t }) {
  const segments = transcriptSegments(result);
  if (!segments.length) return result?.text || t("test.empty");
  return (
    <ol>
      {segments.map((segment, index) => (
        <li key={`${segment.start}-${index}`}>
          <strong className="transcript-speaker">{speakerLabel(segment, t)}</strong>
          <Paragraph>{segment.text}</Paragraph>
        </li>
      ))}
    </ol>
  );
}

export function Latency({ result, t }) {
  const audio = result?.audio_seconds || 0;
  const work = result?.elapsed || 0;
  const scale = Math.max(audio, work, 0.001);
  const ratio = work > 0 && !result?.cached ? audio / work : 0;
  const verdict = !audio ? t("latency.durationOnly") : ratio >= 1
    ? t("latency.faster", { ratio: ratio.toFixed(1) })
    : ratio > 0 ? t("latency.slower", { ratio: (1 / ratio).toFixed(1) }) : "";
  return (
    <div className="latency" id="result" hidden={!result}>
      <Layout>
        <span>{t("latency.audio")}</span>
        <strong id="val-audio">{audio ? t("unit.seconds", { value: audio.toFixed(1) }) : t("latency.unknown")}</strong>
        <i aria-hidden="true"><b id="bar-audio" style={{ width: `${audio / scale * 100}%` }} /></i>
      </Layout>
      <Layout>
        <span id="latency-work-label">{t(result?.cached ? "audio.responseTime" : "latency.work")}</span>
        <strong id="val-work">{t("unit.seconds", { value: work.toFixed(2) })}</strong>
        <i aria-hidden="true"><b id="bar-work" style={{ width: `${work / scale * 100}%` }} /></i>
      </Layout>
      <p id="latency-verdict" data-slow={ratio > 0 && ratio < 1}>{verdict}</p>
    </div>
  );
}
