import { useCallback, useEffect, useState } from "react"
import en from "./en"
import ru from "./ru"

const key = "stt_console_lang"
const messages = { en, ru }
const plurals = { en: new Intl.PluralRules("en"), ru: new Intl.PluralRules("ru") }

function storedLocale() {
  try {
    return localStorage.getItem(key) === "ru" ? "ru" : "en"
  } catch {
    return "en"
  }
}

export function translate(lang, message, params) {
  const template = messages[lang]?.[message] ?? en[message]
  if (template === undefined) return message
  return template.replace(
    /\{(\w+)(?:,\s*plural,\s*((?:\w+\s*\{[^}]*\}\s*)+))?\}/g,
    (whole, name, plural) => {
      const value = params?.[name]
      if (!plural) return value == null ? whole : String(value)
      const forms = Object.fromEntries(Array.from(plural.matchAll(/(\w+)\s*\{([^}]*)\}/g), ([, form, text]) => [form, text]))
      const count = Number(value) || 0
      return (forms[plurals[lang].select(count)] ?? forms.other ?? "").replace(/#/g, String(count))
    },
  )
}

export function useLanguage() {
  const [lang, setLang] = useState(storedLocale)
  const t = useCallback((message, params) => translate(lang, message, params), [lang])
  const changeLanguage = useCallback(next => {
    if (next !== "en" && next !== "ru") return
    setLang(next)
    try {
      localStorage.setItem(key, next)
    } catch {
      // Язык сохранится до закрытия вкладки.
    }
  }, [])
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  return { lang, t, changeLanguage }
}
