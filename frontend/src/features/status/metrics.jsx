import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

function seconds(value, precision, t) {
  return Number.isFinite(value) ? t("unit.seconds", { value: value.toFixed(precision) }) : "—";
}

export function estimateRtf(value) {
  return value ? "×" + (1 / value).toFixed(1) : "—";
}

export function RecentFiles({ t, metrics }) {
  const recent = (metrics.recent || []).slice(0, 4);
  const total = metrics.avg_elapsed_total;
  return (
    <Layout variant="panel stack">
      <Heading level={2} id="recent-title">{t("recent.title")}</Heading>
      <Paragraph id="recent-empty" hidden={!!recent.length}>{t("audio.noMetrics")}</Paragraph>
      <div id="recent" hidden={!recent.length}>
        <Table aria-labelledby="recent-title">
          <colgroup><col /><col className="recent-metric-col" span={3} /></colgroup>
          <TableHeader>
            <TableRow>
              {["file", "audio", "work", "faster"].map(column => (
                <TableHead className="whitespace-normal" key={column} scope="col">{t("recent." + column)}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody id="recent-rows">
            {recent.map((item, index) => (
              <TableRow key={index}>
                <TableCell className="name whitespace-normal" title={item.name}>
                  {item.name}
                  {["microphone", "file", "api"].includes(item.source) && <small className="source-kind">{t("source." + item.source)}</small>}
                </TableCell>
                <TableCell>{seconds(item.audio_seconds || null, 1, t)}</TableCell>
                <TableCell>{seconds(item.elapsed, 2, t)}</TableCell>
                <TableCell>{estimateRtf(item.rtf)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Paragraph id="recent-note" variant="help">{total ? t("recent.average", { value: total.toFixed(2) }) : ""}</Paragraph>
      </div>
    </Layout>
  );
}

export function formatUptime(seconds, t) {
  if (seconds === undefined || seconds === null) return "—";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours) return t("time.hours", { hours, minutes });
  if (minutes) return t("time.minutes", { minutes });
  return t("time.seconds", { seconds });
}
