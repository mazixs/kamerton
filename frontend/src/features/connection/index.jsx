import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useConsole } from "@/app/use-console";
import { Heading, Layout, Paragraph } from "@/components/native/layout";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { CLIENT_BASE_STORAGE, clientBase, requestExamples } from "./examples";
import { CopyButton, ManualCopy, useCopy } from "./copy-controls";
import { ModelPicker } from "./model-picker";
import { OwnerKeys } from "./owner-keys";
import "./connection.css";

const sampleTitles = {
  curl: ["curl", "api.copyCurl"],
  py: ["snippet.python", "api.copyPython"],
  models: ["snippet.models", "api.copyModelRequest"],
  agent: ["api.agentPrompt", "api.copyAgent"],
};

function savedBase(mode) {
  try { return clientBase(localStorage.getItem(CLIENT_BASE_STORAGE) || "", mode); }
  catch { return null; }
}

function RequestExamples({ t, samples, base, owner, bearer, setBearer, copy }) {
  return (
    <Layout variant="panel stack">
      <Heading level={2}>{t("api.requests")}</Heading>
      <label className="check" id="example-key-option" hidden={owner}>
        <input type="checkbox" id="example-key" checked={bearer} onChange={event => setBearer(event.target.checked)} disabled={owner} />
        <span>{t("api.bearer")}</span>
      </label>
      <Paragraph variant="help" id="owner-example-hint" hidden={!owner}>{t("keys.variable")}</Paragraph>
      {Object.entries(sampleTitles).map(([name, [label, copyLabel]]) => {
        const id = "snip-" + name;
        return (
          <Layout variant="snippet" key={id}>
            <Layout variant="titleline">
              <strong>{name === "curl" ? label : t(label)}</strong>
              <CopyButton target={id} text={base && samples[name]} label={t(copyLabel)} copy={copy.copy} t={t} />
            </Layout>
            <ManualCopy target={id} manual={copy.manual} t={t} />
            <pre id={id} lang={name === "agent" ? "en" : undefined}>{samples[name]}</pre>
          </Layout>
        );
      })}
    </Layout>
  );
}

export function Connection({ active }) {
  const { api, status, heads, catalogError, refreshStatus, loadHeads, page, t, lang, mode, key, loggingOut } = useConsole();
  const owner = mode === "owner";
  const localBase = location.origin + "/v1";
  const [address, setAddress] = useState(() => savedBase(mode) || localBase);
  const [bearerChoice, setBearerChoice] = useState(null);
  const [picked, setPicked] = useState("");
  const [modelList, setModelList] = useState({ response: null, error: null, loading: true });
  const [localDeployment, setLocalDeployment] = useState(null);
  const [deploymentError, setDeploymentError] = useState(null);
  const request = useRef(0);
  const addressInput = useRef(null);
  const lastStatus = useRef(null);
  const bearer = owner || (bearerChoice ?? !!status?.api_key_set);
  const base = clientBase(address, mode);
  const data = modelList.response?.data || [];
  const selected = data.some(item => item.id === picked) ? picked : data[0]?.id || "";
  const clipboard = useCopy(JSON.stringify([page, lang, base, bearer, selected]), t, true);
  const addressError = base ? "" : t(owner ? "auth.addressInvalid" : "api.invalid");

  const load = useCallback(async () => {
    const number = ++request.current;
    setModelList(current => ({ ...current, loading: true, error: null }));
    try {
      const result = await api(owner ? "/api/client-models" : "/v1/models");
      if (!Array.isArray(result?.data) || !result.data.every(row => /^[a-z\d][a-z\d._-]*$/i.test(row?.id || ""))) {
        throw new Error("api.modelListFailed");
      }
      if (number === request.current) setModelList({ response: result, loading: false, error: null });
    } catch (err) {
      if (number === request.current) setModelList({ response: null, loading: false, error: err });
    }
  }, [api, owner]);

  useEffect(() => {
    if (active && mode) load();
    return () => { request.current += 1; };
  }, [active, key, mode, load]);

  const phase = status?.status;
  const variant = status?.engine?.variant;
  useEffect(() => {
    const previous = lastStatus.current;
    lastStatus.current = phase ? [phase, variant] : null;
    if (active && previous && phase && (previous[0] !== phase || previous[1] !== variant)) load();
  }, [active, load, phase, variant]);

  useEffect(() => { addressInput.current?.setCustomValidity(addressError); }, [addressError]);

  function resetAddress() {
    setAddress(localBase);
    try { localStorage.removeItem(CLIENT_BASE_STORAGE); } catch { /* Только в этой вкладке. */ }
    addressInput.current.focus();
  }

  function saveAddress() {
    if (!base) return;
    setAddress(base);
    try { localStorage.setItem(CLIENT_BASE_STORAGE, base); } catch { /* Только в этой вкладке. */ }
  }

  const localDeploymentControl = {
    pending: localDeployment,
    errorFor(id) {
      if (deploymentError?.id !== id) return "";
      const { error } = deploymentError;
      if (typeof error.key === "string") return error.message;
      return error.status ? t("api.error", { status: error.status }) : t("models.noConnection");
    },
    async deploy(config) {
      if (localDeployment) return;
      setLocalDeployment(config.variant);
      setDeploymentError(null);
      try {
        await api("/api/deploy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) });
      } catch (error) {
        setDeploymentError({ id: config.variant, error });
      } finally {
        await refreshStatus();
        setLocalDeployment(null);
      }
    },
  };
  const responseError = modelList.error?.message === "api.modelListFailed" ? new Error(t("api.modelListFailed")) : modelList.error;
  const intro = t("connect.intro", { model: "\u0000" }).split("\u0000");
  const samples = requestExamples(base, selected, bearer, t("snippet.file"));
  const heading = owner ? "auth.addressHelp" : "api.addressHelp";

  return (
    <>
      <Layout variant="stack">
        <Layout variant="panel stack" role="region" aria-labelledby="client-settings-title">
          <Heading level={2} id="client-settings-title">{t("api.clientSettings")}</Heading>
          <Field className="field" data-invalid={!base || undefined}>
            <FieldLabel htmlFor="base-url">Base URL</FieldLabel>
            <Layout variant="copy-row">
              <Input type="url" id="base-url" ref={addressInput} dir="ltr" required autoComplete="off" spellCheck={false}
                aria-describedby="address-help address-error" aria-invalid={!base}
                value={address} onChange={event => setAddress(event.target.value)} onBlur={saveAddress} />
              <CopyButton target="base-url" text={base} label={t("api.copyBase")} copy={clipboard.copy} t={t} icon />
            </Layout>
            <ManualCopy target="base-url" manual={clipboard.manual} t={t} />
          </Field>
          <Paragraph id="address-help" variant="help">{t(heading)}</Paragraph>
          <p role="status" id="address-error" className="error">{addressError}</p>
          <Button type="button" variant="ghost" id="reset-origin" onClick={resetAddress}>{t("api.reset")}</Button>
          <Paragraph variant="help" id="connect-intro">
            {intro.map((part, index) => <Fragment key={index}>{index > 0 && <code>model</code>}{part}</Fragment>)}
          </Paragraph>
          <div id="connect-docs">
            <a id="link-docs" href={mode === "local" && key ? "/api/docs?api_key=" + encodeURIComponent(key) : "/api/docs"}
              target="_blank" rel="noreferrer">{t(owner ? "auth.docs" : "connect.swagger")}</a>
          </div>
        </Layout>
        <ModelPicker t={t} heads={heads} status={status} catalogError={catalogError}
          request={{ ...modelList, error: responseError }} response={modelList.response} selected={selected} select={setPicked}
          load={() => { loadHeads(); load(); }} deployment={localDeploymentControl} copy={clipboard} />
        {owner && <OwnerKeys api={api} active={active} page={page} lang={lang} t={t} loggingOut={loggingOut} />}
      </Layout>
      <RequestExamples t={t} samples={samples} base={base} owner={owner} bearer={bearer} setBearer={setBearerChoice} copy={clipboard} />
      <div id="live" className="toast" role="status">{clipboard.feedback}</div>
    </>
  );
}
