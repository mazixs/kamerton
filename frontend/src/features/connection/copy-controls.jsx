import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";

export function useCopy(scope, t, temporary = false) {
  const current = useRef(scope);
  const request = useRef(0);
  const [result, setResult] = useState(null);
  useLayoutEffect(() => { current.current = scope; }, [scope]);
  useLayoutEffect(() => () => { request.current += 1; }, []);

  const clear = useCallback(() => {
    request.current += 1;
    setResult(null);
  }, []);

  async function copy(id, value) {
    if (!value) return;
    const number = ++request.current;
    setResult(null);
    let copied = false;
    try {
      await navigator.clipboard.writeText(value);
      copied = true;
    } catch {
      // На сайтах без Clipboard API оставляем доступное поле для ручного копирования.
    }
    if (current.current === scope && number === request.current) setResult({ id, value, scope, copied });
  }

  const visible = result?.scope === scope ? result : null;
  useEffect(() => {
    if (!temporary || !visible?.copied) return;
    const timeout = setTimeout(() => setResult(current => current === visible ? null : current), 2800);
    return () => clearTimeout(timeout);
  }, [temporary, visible]);
  return {
    copy,
    clear,
    feedback: visible?.copied ? t("btn.copied") : "",
    manual: visible && !visible.copied ? visible : null,
  };
}

export function CopyButton({ id, target, text, label, copy, t, icon = false, iconOnly = false, autoFocus = false }) {
  return (
    <Button
      id={id}
      type="button"
      className="copy"
      variant="outline"
      size={iconOnly ? "icon" : "sm"}
      data-target={target}
      aria-label={label}
      disabled={!text}
      autoFocus={autoFocus}
      onClick={() => copy(target, text)}
    >
      {icon && <Copy aria-hidden="true" data-icon="inline-start" />}
      {!iconOnly && <span>{t("btn.copy")}</span>}
    </Button>
  );
}

export function ManualCopy({ target, manual, t }) {
  const field = useRef(null);
  const value = manual?.id === target ? manual.value : null;
  useLayoutEffect(() => {
    if (value !== null && field.current) {
      field.current.focus();
      field.current.select();
    }
  }, [value]);
  if (value === null) return null;
  const id = "manual-copy-" + target;
  return (
    <Field className="manual">
      <FieldLabel htmlFor={id}>{t("copy.manual")}</FieldLabel>
      <Textarea id={id} ref={field} readOnly value={value} rows={3} />
    </Field>
  );
}
