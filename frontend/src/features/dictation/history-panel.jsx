import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/copy-button";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Transcript } from "./transcript";
import { transcriptText } from "./history.js";

const PAGE_SIZE = 5;

export function HistoryPanel({ entries, retention, error, page, setPage, t, lang, active }) {
  const total = Math.max(1, Math.ceil(entries.length / PAGE_SIZE));
  const current = Math.min(page, total - 1);
  const date = new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "short" });
  return (
    <section className="dictation-history" aria-labelledby="history-title">
      <Heading level={2} id="history-title">{t("history.title")}</Heading>
      <Paragraph variant="help" id="history-empty">
        {!entries.length && !error && t(retention === "off" ? "history.disabled" : "history.empty")}
      </Paragraph>
      <p className="error help" id="history-error" role="status">{error && t("history.storageFailed")}</p>
      <Layout variant="history-entries" id="history-entries">
        {entries.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map((entry) => {
          const target = `history-transcript-${entry.id}`;
          return (
            <details key={entry.id} data-id={entry.id}>
              <summary>{entry.filename}<time dateTime={new Date(entry.at).toISOString()}>{date.format(entry.at)}</time></summary>
              <Layout variant="history-entry-body">
                <div className="transcript" id={target} tabIndex={0}><Transcript result={entry.result} t={t} /></div>
                <Layout variant="actions">
                  <CopyButton t={t} target={target} active={active} value={transcriptText(entry.result, t)} />
                </Layout>
              </Layout>
            </details>
          );
        })}
      </Layout>
      <nav className="history-pages" id="history-pages" aria-label={t("history.pages")} hidden={total <= 1}>
        <Button type="button" variant="ghost" size="sm" id="history-prev" onClick={() => setPage(current - 1)} disabled={current === 0}>{t("history.previous")}</Button>
        <span className="small" id="history-page" role="status">{t("history.page", { current: current + 1, total })}</span>
        <Button type="button" variant="ghost" size="sm" id="history-next" onClick={() => setPage(current + 1)} disabled={current === total - 1}>{t("history.next")}</Button>
      </nav>
    </section>
  );
}
