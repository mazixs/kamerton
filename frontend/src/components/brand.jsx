import { Icon } from "./icons"
import { LabelText, Layout } from "./native/layout"

export function Brand({ t, href }) {
  return (
    <Layout variant="brand" href={href}>
      <Icon name="fork" className="logo" />
      <Layout>
        <LabelText>{t("brand.name")}</LabelText>
        <LabelText variant="brand-caption">{t("brand.sub")}</LabelText>
      </Layout>
    </Layout>
  )
}
