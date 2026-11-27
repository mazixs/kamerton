import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const languages = ["en", "ru"]

export function LanguageSwitch({ lang, t, changeLanguage }) {
  return (
    <ToggleGroup className="lang" type="single" value={lang} onValueChange={changeLanguage} aria-label={t("lang.label")}>
      {languages.map(language => (
        <ToggleGroupItem key={language} value={language} data-lang={language} lang={language}
          className="lang-option">
          {language.toUpperCase()}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
