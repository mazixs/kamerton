import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function CopyButton({ t, target, value, active = true, hidden, className, variant = "ghost", label }) {
  const [feedback, setFeedback] = useState(null);
  const fallback = useRef(null);
  const request = useRef(0);
  const resetTimer = useRef(null);

  useEffect(() => {
    setFeedback(null);
    return () => {
      request.current += 1;
      clearTimeout(resetTimer.current);
    };
  }, [value, active]);

  useEffect(() => {
    if (feedback === "manual" && fallback.current) {
      fallback.current.focus();
      fallback.current.select();
    }
  }, [feedback]);

  async function copy() {
    if (!value) return;
    clearTimeout(resetTimer.current);
    const id = ++request.current;
    try {
      await navigator.clipboard.writeText(value);
      if (request.current !== id) return;
      setFeedback("copied");
      resetTimer.current = setTimeout(() => setFeedback(null), 2800);
    } catch {
      if (request.current === id) setFeedback("manual");
    }
  }

  return (
    <div className="copy-control" hidden={hidden}>
      <Button type="button" variant={variant} size="sm" className={className} data-target={target} onClick={copy} disabled={!value}>
        {label ?? t("btn.copy")}
      </Button>
      <span role="status" hidden={feedback !== "copied"} className="small">{feedback === "copied" && t("btn.copied")}</span>
      {feedback === "manual" && (
        <label className="field manual">
          {t("copy.manual")}
          <Textarea ref={fallback} readOnly value={value} rows={3} />
        </label>
      )}
    </div>
  );
}
