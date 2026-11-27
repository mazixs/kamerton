import { fold } from "./phrases"

export function glossaryCoverage(payload, entries, dirty, model, t) {
  const dropped = new Set((payload?.dropped || []).map(fold))
  const total = entries.length
  const head = payload?.variant ? t("glossary.headNamed", { variant: payload.variant }) : t("glossary.headAny")

  if (payload?.mode === "prompt" || payload?.mode === "unsupported") {
    return {
      dropped,
      text: t("glossary.mode." + payload.mode, { model: model || payload.variant }),
      help: dirty ? t("glossary.unsaved") : "",
    }
  }
  if (dirty) return { dropped, text: t("glossary.staged") }
  if (!total) return { dropped, text: "" }
  if (payload?.usable_count === null) return { dropped, text: t("glossary.notDownloaded") }
  if (!dropped.size) {
    return { dropped, text: t("glossary.allReach") + (payload?.approximate ? t("glossary.approximate") : "") }
  }
  const alphabet = payload?.alphabet
  const missing = alphabet ? [
    !alphabet.latin && t("glossary.latin"),
    !alphabet.digits && t("glossary.digits"),
  ].filter(Boolean) : []
  const help = missing.length
    ? t("glossary.missingList", { head, missing: missing.join(t("glossary.listSeparator")) })
      + (alphabet.latin ? "" : t("glossary.latinAdvice"))
    : t("glossary.missingSymbols", { head })
  return { dropped, loss: true, text: t("glossary.lost", { dropped: dropped.size, total }), help }
}
