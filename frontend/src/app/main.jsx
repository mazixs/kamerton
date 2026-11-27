import { createRoot } from "react-dom/client"
import "@/styles/theme.css"
import "@/styles/shell.css"
import "@/styles/workspace.css"
import "@/styles/access.css"
import { ConsoleProvider } from "./console-provider"
import { Workspace } from "./workspace"

createRoot(document.getElementById("root")).render(<ConsoleProvider><Workspace /></ConsoleProvider>)
