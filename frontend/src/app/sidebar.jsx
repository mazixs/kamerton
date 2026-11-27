import { Brand } from "@/components/brand"
import { Icon } from "@/components/icons"
import { LanguageSwitch } from "@/components/language-switch"
import { LabelText, Layout } from "@/components/native/layout"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { HOME_PAGE, navigation } from "./routes"
import { useConsole } from "./use-console"

const icons = { benchmarks: "text", glossary: "gloss", journal: "log" }
const homeHref = "#" + HOME_PAGE

export function Sidebar() {
  const { page, status, statusError, t, lang, changeLanguage } = useConsole()
  const label = statusError ? t("state.offline") : status ? t("state." + status.status) : "…"
  return (
    <Layout variant="rail-column">
      <Layout role="complementary" variant="rail">
        <Brand t={t} href={homeHref} />
        <Layout role="navigation" id="railnav" aria-label={t("nav.label")}>
          {navigation.map(group => (
            <Layout variant="navgroup" key={group[0]}>
              {group.map(route => (
                <a key={route} href={"#" + route} aria-current={route === page ? "page" : undefined}>
                  <Icon name={icons[route] ?? route} />
                  <LabelText>{t("page." + route)}</LabelText>
                </a>
              ))}
            </Layout>
          ))}
        </Layout>
        <Layout variant="railfoot">
          <a id="state-pill" href="#status" data-state={status?.status ?? "unknown"}>
            <i className="lamp" /><LabelText id="state-label">{label}</LabelText>
          </a>
          <LanguageSwitch {...{ t, lang, changeLanguage }} />
        </Layout>
      </Layout>
    </Layout>
  )
}

export function MobileHeader() {
  const { page, setPage, t, lang, changeLanguage } = useConsole()
  return (
    <header className="mobile">
      <Brand t={t} href={homeHref} />
      <LanguageSwitch {...{ t, lang, changeLanguage }} />
      <NativeSelect id="mobile-nav" value={page} onChange={event => setPage(event.target.value)} aria-label={t("nav.label")}>
        {navigation.flat().map(route => <NativeSelectOption key={route} value={route}>{t("page." + route)}</NativeSelectOption>)}
      </NativeSelect>
    </header>
  )
}
