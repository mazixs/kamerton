import { useEffect, useRef } from "react";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { deployBusy, detailText, modelFailure } from "@/features/models/model-state";
import { CopyButton, ManualCopy } from "./copy-controls";

export function ModelPicker({ t, heads, response, catalogError, request, selected, select, load, status, deployment, copy }) {
  const picker = useRef(null);
  const summary = useRef(null);
  const rows = new Map(heads.map(head => [head.api_id, head]));
  const available = new Set((response?.data || []).map(({ id }) => id));
  for (const id of available) if (!rows.has(id)) rows.set(id, null);
  const busy = deployBusy(status);
  const responseStatus = request.loading ? t("state.loading")
    : request.error?.message || (available.size ? "" : t("api.noModels"));
  const catalogStatus = catalogError ? t(heads.length ? "models.catalogStale" : "models.catalogFailed") : "";

  useEffect(() => {
    function outside(event) {
      if (picker.current?.open && !picker.current.contains(event.target)) picker.current.open = false;
    }
    document.addEventListener("click", outside);
    return () => document.removeEventListener("click", outside);
  }, []);

  function close() {
    picker.current.open = false;
    summary.current.focus();
  }

  return (
    <Layout variant="panel stack" role="region" aria-labelledby="service-models-title">
      <Heading level={2} id="service-models-title">{t("api.currentModels")}</Heading>
      <Paragraph variant="help" id="models-hint">{t("api.modelSelection")}</Paragraph>
      <Field className="field">
        <FieldLabel id="client-model-label">{t("api.modelId")}</FieldLabel>
        <Layout variant="copy-row api-model-field">
          <details
            id="client-model-picker"
            ref={picker}
            onKeyDown={event => {
              if (event.key !== "Escape" || !picker.current.open) return;
              event.preventDefault();
              close();
            }}
          >
            <summary ref={summary} aria-labelledby="client-model-label client-model" aria-describedby="models-hint model-list-status">
              <span id="client-model">{selected || t("api.selectModel")}</span>
            </summary>
            <ul id="client-model-list">
              {[...rows].map(([id, head]) => {
                const choose = available.has(id);
                const active = busy && head && status?.deploying === head.id;
                const sending = !!head && deployment.pending === head.id;
                const error = head ? deployment.errorFor(head.id) || modelFailure(head.id, status, t) : "";
                const hasAction = !choose && !!head && (!head.downloaded || error || active || sending);
                const progress = active && Number.isFinite(status.download_percent) ? " · " + status.download_percent + "%" : "";
                const message = error || (sending ? t("settings.wait") : active ? detailText(status, t) + progress : "");
                return (
                  <li className="api-model-row" data-model-id={id} key={id}>
                    {choose ? (
                      <Button type="button" variant="ghost" className="api-model-select soft" aria-pressed={selected === id}
                        onClick={() => { select(id); close(); }}>
                        {id === "kamerton" ? t("api.modelAlias", { id }) : id}
                      </Button>
                    ) : (
                      <span className="muted">
                        <code>{id}</code><small>{t(head?.downloaded ? "storage.unavailable" : "models.notDownloaded")}</small>
                      </span>
                    )}
                    {hasAction && <Button type="button" variant="ghost" size="sm" className="soft" aria-label={t("api.deployOne", { model: id })}
                      disabled={!status?.defaults || busy || !!deployment.pending}
                      onClick={() => deployment.deploy({ variant: head.id })}>{t("head.deploy")}</Button>}
                    <p className={error ? "error" : "help"} role="status" hidden={!message}>{message}</p>
                  </li>
                );
              })}
            </ul>
          </details>
          <CopyButton target="client-model" text={selected} label={t("api.copyModel")} copy={copy.copy} t={t} icon iconOnly />
        </Layout>
        <ManualCopy target="client-model" manual={copy.manual} t={t} />
      </Field>
      <p className="help" id="model-list-status" role="status">{[responseStatus, catalogStatus].filter(Boolean).join(" ")}</p>
      {(request.error || catalogError) && <Button type="button" variant="ghost" id="model-list-retry" onClick={load}>{t("head.retry")}</Button>}
      <details className="snippet" id="service-models">
        <summary>{t("api.modelResponse")}</summary>
        <pre id="model-response">{response ? JSON.stringify(response, null, 2) : responseStatus}</pre>
      </details>
    </Layout>
  );
}
