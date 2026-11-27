export function nativeStyleSheet() {
  let reference
  let base

  return {
    name: "kamerton-native-stylesheet",
    apply: "build",
    configResolved(config) {
      base = config.base
    },
    buildStart() {
      reference = this.emitFile({
        type: "asset",
        name: "react-native-web.css",
        source: "/* React Native Web inserts its rules into this stylesheet using CSSOM. */\n",
      })
    },
    transformIndexHtml: {
      order: "post",
      handler(_html, { chunk }) {
        const file = this.getFileName(reference)
        // FastAPI разрешает загрузку стилей до входа по графу манифеста.
        chunk.viteMetadata.importedAssets.add(file)
        // React Native Web 0.21.4 использует .sheet элемента с этим id.
        // Внешний link оставляет в силе запрет встроенных стилей в CSP.
        return [{
          tag: "link",
          attrs: { id: "react-native-stylesheet", rel: "stylesheet", href: `${base}${file}` },
          injectTo: "head-prepend",
        }]
      },
    },
  }
}
