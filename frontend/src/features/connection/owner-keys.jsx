import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { CopyButton, ManualCopy, useCopy } from "./copy-controls";

function metadata(result) {
  if (!Array.isArray(result.keys)) throw new Error("Invalid key list");
  return result.keys.filter(row => !row.revoked_at).map(({ id, name, created_at }) => ({ id, name, created_at }));
}

export function OwnerKeys({ api, active, page, lang, t, loggingOut }) {
  const [rows, setRows] = useState(null);
  const [listError, setListError] = useState(false);
  const [notice, setNotice] = useState("");
  const [secret, setSecret] = useState("");
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState(false);
  const listRequest = useRef(0);
  const session = useRef(0);
  const currentSelection = useRef(null);
  const currentPage = useRef(page);
  const nameField = useRef(null);
  const secretDialog = useRef(null);
  const revokeDialog = useRef(null);
  const initialPage = useRef(page);
  const issuer = location.origin + "/v1";
  const clipboard = useCopy(page + "/" + lang + "/" + !!secret, t);
  const clearCopy = clipboard.clear;

  const load = useCallback(async () => {
    const token = ++listRequest.current;
    setListError(false);
    try {
      const data = metadata(await api("/api/keys"));
      if (token === listRequest.current) setRows(data);
    } catch {
      if (token === listRequest.current) setListError(true);
    }
  }, [api]);

  const erase = useCallback(() => {
    clearCopy();
    setSecret("");
    if (secretDialog.current?.open) secretDialog.current.close();
  }, [clearCopy]);

  useLayoutEffect(() => {
    currentPage.current = page;
    if (page === initialPage.current) return;
    initialPage.current = page;
    ++listRequest.current;
    erase();
    if (revokeDialog.current?.open) revokeDialog.current.close();
    setSelected(null);
    setNotice("");
  }, [page, erase]);

  useLayoutEffect(() => {
    if (secret && secretDialog.current && !secretDialog.current.open) {
      secretDialog.current.showModal();
      secretDialog.current.querySelector("#key-copy").focus();
    }
  }, [secret]);

  useLayoutEffect(() => {
    currentSelection.current = selected;
    if (selected && revokeDialog.current && !revokeDialog.current.open) {
      revokeDialog.current.showModal();
      revokeDialog.current.querySelector("#revoke-cancel").focus();
    }
  }, [selected]);

  useEffect(() => {
    if (active && !loggingOut) load();
  }, [active, load, loggingOut]);

  useLayoutEffect(() => {
    session.current += 1;
    erase();
    if (revokeDialog.current?.open) revokeDialog.current.close();
    setSelected(null);
    setCreating(false);
    setRevoking(false);
  }, [loggingOut, erase]);

  useEffect(() => {
    const hide = () => {
      session.current += 1;
      ++listRequest.current;
      flushSync(erase);
    };
    window.addEventListener("pagehide", hide);
    return () => {
      window.removeEventListener("pagehide", hide);
      session.current += 1;
      ++listRequest.current;
    };
  }, [erase]);

  async function create(event) {
    event.preventDefault();
    if (creating || loggingOut) return;
    const input = nameField.current;
    const name = input.value.trim();
    if (!name) { input.value = ""; input.reportValidity(); return; }
    const token = session.current;
    setCreating(true);
    setNotice("");
    try {
      const result = await api("/api/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (token !== session.current) return;
      if (typeof result.key !== "string" || !result.key) throw new Error("Missing client key");
      input.value = "";
      setSecret(result.key);
    } catch {
      if (token === session.current) setNotice("keys.createFailed");
    } finally {
      if (token === session.current) {
        setCreating(false);
        if (currentPage.current === "api") load();
      }
    }
  }

  async function revoke() {
    if (!selected || revoking || loggingOut) return;
    const token = session.current;
    const row = selected;
    setRevoking(true);
    setRevokeError(false);
    try {
      await api("/api/keys/" + encodeURIComponent(row.id) + "/revoke", { method: "POST" });
      if (token !== session.current) return;
      ++listRequest.current;
      setRows(previous => previous?.filter(item => item.id !== row.id) || []);
      if (currentPage.current === "api") {
        setNotice("keys.revokedNotice");
        if (revokeDialog.current.open && currentSelection.current?.id === row.id) {
          revokeDialog.current.close();
          nameField.current.focus();
        }
        load();
      }
    } catch {
      if (token === session.current && currentPage.current === "api") {
        if (revokeDialog.current.open && currentSelection.current?.id === row.id) setRevokeError(true);
        else setNotice("keys.revokeFailed");
      }
    } finally {
      if (token === session.current) setRevoking(false);
    }
  }

  function secretClosed() {
    // Удаляем значение и поле ручного копирования даже при Escape.
    if (secretDialog.current?.open) return;
    erase();
    if (currentPage.current === "api") nameField.current?.focus();
  }

  const date = new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeStyle: "short" });
  const listState = listError ? "keys.listFailed" : rows === null ? "state.loading" : rows.length ? "" : "keys.empty";

  return (
    <Layout variant="panel stack" role="region" id="owner-keys" aria-labelledby="key-title">
      <Heading level={2} id="key-title">{t("keys.title")}</Heading>
      <Paragraph variant="help">{t("keys.intro")}</Paragraph>
      <form id="key-form" className="stack" onSubmit={create}>
        <FieldGroup>
          <Field className="field">
            <FieldLabel htmlFor="key-name">{t("keys.name")}</FieldLabel>
            <Input id="key-name" name="name" type="text" ref={nameField} required autoComplete="off" aria-describedby="key-hint" />
            <FieldDescription className="help" id="key-hint">{t("keys.hint")}</FieldDescription>
          </Field>
        </FieldGroup>
        <Button type="submit" id="key-create" disabled={creating || loggingOut}>{t("keys.create")}</Button>
      </form>
      <p id="key-notice" className={notice.endsWith("Failed") ? "error" : undefined} role="status">{notice && t(notice)}</p>
      <p id="key-list-status" role="status" className="help">{listState && t(listState)}</p>
      {listError && <Button type="button" variant="ghost" id="key-retry" onClick={load}>{t("head.retry")}</Button>}
      <ul id="key-list" aria-labelledby="key-title">
        {(rows || []).map(row => (
          <li key={row.id}>
            <Layout variant="titleline">
              <strong>{row.name}</strong>
              <Button type="button" variant="ghost" aria-label={t("keys.revokeNamed", { name: row.name })} onClick={() => {
                setRevokeError(false);
                setSelected(row);
              }}>{t("keys.revoke")}</Button>
            </Layout>
            <code>ID: {row.id}</code>
            <Paragraph variant="help">{t("keys.created", { date: date.format(new Date(row.created_at)) })}</Paragraph>
          </li>
        ))}
      </ul>
      {createPortal(
        <>
          <dialog id="secret-dialog" ref={secretDialog} aria-labelledby="secret-title" aria-describedby="secret-hint"
            onClose={secretClosed} onCancel={event => { event.preventDefault(); erase(); }}>
            <Layout variant="stack">
              <Heading level={2} id="secret-title">{t("keys.secretTitle")}</Heading>
              <Paragraph id="secret-hint">{t("keys.secretHint")}</Paragraph>
              <dl className="credentials">
                <div>
                  <dt>Base URL</dt>
                  <dd className="copy-row">
                    <code id="key-base" dir="ltr">{secret && issuer}</code>
                    <CopyButton target="key-base" text={secret ? issuer : null} label={t("api.copyBase")} copy={clipboard.copy} t={t} icon />
                  </dd>
                  {clipboard.manual?.id === "key-base" && <dd><ManualCopy target="key-base" manual={clipboard.manual} t={t} /></dd>}
                </div>
                <div>
                  <dt>{t("api.apiKey")}</dt>
                  <dd className="copy-row">
                    <code id="key-secret" dir="ltr">{secret}</code>
                    <CopyButton id="key-copy" target="key-secret" text={secret} label={t("api.copyKey")} copy={clipboard.copy} t={t} icon />
                  </dd>
                  {clipboard.manual?.id === "key-secret" && <dd><ManualCopy target="key-secret" manual={clipboard.manual} t={t} /></dd>}
                </div>
              </dl>
              <Layout variant="actions"><Button type="button" id="key-dismiss" onClick={erase}>{t("keys.close")}</Button></Layout>
              <p role="status" id="key-copy-status">{clipboard.feedback}</p>
            </Layout>
          </dialog>
          <dialog id="revoke-dialog" ref={revokeDialog} aria-labelledby="revoke-title" aria-describedby="revoke-description"
            onClose={() => { if (!revokeDialog.current?.open) setSelected(null); }}>
            <Layout variant="stack">
              <Heading level={2} id="revoke-title">{t("keys.revokeTitle")}</Heading>
              <Paragraph id="revoke-description">{selected && t("keys.revokeHint", { name: selected.name, id: selected.id })}</Paragraph>
              <Layout variant="actions">
                <Button type="button" variant="outline" id="revoke-cancel" onClick={() => revokeDialog.current.close()}>
                  {t(revoking ? "keys.close" : "keys.cancel")}
                </Button>
                <Button type="button" variant="destructive" id="revoke-confirm" onClick={revoke} disabled={revoking}>{t("keys.revoke")}</Button>
              </Layout>
              <p id="revoke-error" className="error" role="status">{revokeError && t("keys.revokeFailed")}</p>
            </Layout>
          </dialog>
        </>, document.body,
      )}
    </Layout>
  );
}
