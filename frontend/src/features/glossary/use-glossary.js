import { useCallback, useEffect, useRef, useState } from "react"

import { entryText, parseGlossary } from "./phrases"

export function useGlossary(api, active, variant, phase, count) {
  const [data, setData] = useState({ payload: null, entries: [], applied: "", issues: [] })
  const [error, setError] = useState(null)
  const read = useRef(null)
  const saving = useRef(false)
  const load = useCallback(async ({ keepDraft = true, issues } = {}) => {
    read.current?.abort()
    const controller = new AbortController()
    read.current = controller
    try {
      const payload = await api("/api/glossary", { signal: controller.signal })
      if (controller.signal.aborted) return false
      const entries = parseGlossary(payload.text)
      const applied = entryText(entries)
      setData((current) => {
        const overrides = issues ?? (current.applied === applied ? current.overrides : null)
        return {
          entries: keepDraft && current.payload && entryText(current.entries) !== current.applied ? current.entries : entries,
          applied,
          issues: overrides ?? payload.issues ?? [],
          overrides,
          payload,
        }
      })
      setError(null)
      return true
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason)
      return false
    } finally {
      if (read.current === controller) read.current = null
    }
  }, [api])

  useEffect(() => {
    if (active && !saving.current && phase !== "downloading" && phase !== "starting") load()
  }, [active, variant, phase, count, load])
  useEffect(() => () => read.current?.abort(), [])

  const setEntries = (entries) => setData((current) => ({ ...current, entries }))
  const setIssues = (issues) => setData((current) => ({ ...current, issues, overrides: issues }))
  const pauseRead = () => {
    saving.current = true
    read.current?.abort()
  }
  const resumeRead = () => { saving.current = false }
  return { ...data, error, load, setEntries, setIssues, pauseRead, resumeRead }
}
