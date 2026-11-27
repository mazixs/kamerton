import { StyleSheet, Text, View } from "react-native"

const styles = StyleSheet.create({
  layout: { alignContent: "normal", display: "block", position: "static", zIndex: "auto" },
})

export function Layout({ variant, dataSet, hidden, style, ...props }) {
  return (
    <View
      {...props}
      dataSet={{ ...dataSet, layout: variant ?? "", hidden: hidden ? "true" : undefined }}
      style={[styles.layout, style]}
    />
  )
}

function NativeText({ variant, dataSet, hidden, ...props }) {
  return (
    <Text
      {...props}
      dataSet={{ ...dataSet, nativeText: "", type: variant, hidden: hidden ? "true" : undefined }}
    />
  )
}

export function Heading({ level = 2, ...props }) {
  return <NativeText {...props} role="heading" aria-level={level} />
}

export function Paragraph(props) {
  return <NativeText {...props} role="paragraph" />
}

export function LabelText(props) {
  return <NativeText {...props} />
}
