import { fileURLToPath } from "node:url"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"
import { nativeStyleSheet } from "./scripts/native-stylesheet.js"

const localBackend = "http://127.0.0.1:8080"
const paths = ["/api", "/v1", "/auth", "/health", "/static/capture-worklet.js"]
const proxy = Object.fromEntries(paths.map(path => [path, localBackend]))

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/" : "/",
  plugins: [
    react(),
    tailwindcss(),
    nativeStyleSheet(),
    {
      name: "kamerton-dev-login",
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          if (req.url === "/login") req.url = "/login.html"
          next()
        })
      },
    },
  ],
  resolve: {
    alias: [
      { find: /^react-native$/, replacement: "react-native-web" },
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
    ],
  },
  server: { proxy },
  build: {
    manifest: true,
    target: ["chrome109", "firefox115", "safari16.4"],
    rollupOptions: {
      input: {
        index: fileURLToPath(new URL("./index.html", import.meta.url)),
        login: fileURLToPath(new URL("./login.html", import.meta.url)),
      },
    },
  },
}))
