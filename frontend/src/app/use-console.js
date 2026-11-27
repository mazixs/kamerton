import { createContext, useContext } from "react"

export const ConsoleContext = createContext(null)

export function useConsole() {
  const consoleState = useContext(ConsoleContext)
  if (!consoleState) throw new Error("ConsoleProvider is missing")
  return consoleState
}
