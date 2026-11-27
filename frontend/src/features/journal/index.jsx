import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useConsole } from "@/app/use-console";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Field, FieldLabel } from "@/components/ui/field";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";

const options = {
  category: ["all", "deploy", "engine"],
  level: ["all", "info", "warning", "error"],
  period: ["all", "hour", "day"],
};

export function Journal({ active }) {
  const { api, logs, t, lang } = useConsole();
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ category: "all", level: "all", period: "all" });
  const [follow, setFollow] = useState(true);
  const logArea = useRef(null);

  useEffect(() => {
    if (!active) return;
    let current = true;
    api("/api/journal").then(result => {
      if (!current) return;
      setEvents(result.events);
      setError(null);
    }).catch(err => { if (current) setError(err); });
    return () => { current = false; };
  }, [active, api]);

  useLayoutEffect(() => {
    if (follow && logArea.current) logArea.current.scrollTop = logArea.current.scrollHeight;
  }, [follow, logs, active]);

  const after = filters.period === "hour" ? Date.now() - 3_600_000 : filters.period === "day" ? Date.now() - 86_400_000 : 0;
  const filtered = (events || []).filter(item =>
    (filters.category === "all" || filters.category === item.category) &&
    (filters.level === "all" || filters.level === item.level) && Date.parse(item.at) >= after);
  const date = new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "medium" });
  const note = error?.message || (!events ? t("state.loading") : !filtered.length ? t("journal.empty") : "");

  return (
    <>
      <Layout variant="panel stack">
        <Heading level={2}>{t("journal.recent")}</Heading>
        <Paragraph variant="help">{t("journal.limit")}</Paragraph>
        <Layout variant="filters">
          {Object.entries(options).map(([filter, values]) => (
            <Field className="field" key={filter}>
              <FieldLabel htmlFor={"journal-" + filter}>{t("journal." + filter)}</FieldLabel>
              <NativeSelect id={"journal-" + filter} value={filters[filter]}
                onChange={event => setFilters({ ...filters, [filter]: event.target.value })}>
                {values.map(value => <NativeSelectOption key={value} value={value}>{t("journal." + value)}</NativeSelectOption>)}
              </NativeSelect>
            </Field>
          ))}
        </Layout>
        <p id="journal-note" role="status">{note}</p>
        <ol id="journal-events">
          {filtered.map((event, index) => {
            const params = event.params || {};
            const key = "event." + event.code;
            const message = t(key, { ...params, kind: t("reason." + (params.kind || "other")), variant: params.variant || "—" });
            return (
              <li className="logrow" key={event.at + "/" + event.code + "/" + index} data-level={event.level}>
                <time dateTime={event.at}>{date.format(new Date(event.at))}</time>
                <div>
                  <span className="logmeta">{t("journal." + event.category)} · {t("journal." + event.level)}</span>
                  <span>{message === key ? event.code : message}</span>
                  {event.code === "download.failed" && params.running && <span className="logmeta">{t("event.previous", params)}</span>}
                </div>
              </li>
            );
          })}
        </ol>
      </Layout>
      <details className="panel" id="tech-logs" onToggle={() => {
        if (follow && logArea.current) logArea.current.scrollTop = logArea.current.scrollHeight;
      }}>
        <summary>{t("journal.logs")}</summary>
        <label className="check">
          <input id="log-follow" type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)} />
          <span>{t("logs.follow")}</span>
        </label>
        <pre id="logs" ref={logArea} tabIndex={0} aria-label={t("journal.logs")}>{logs.join("\n")}</pre>
      </details>
    </>
  );
}
