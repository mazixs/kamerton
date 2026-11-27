import { reports } from "./reports"

const overview = {
  human: ["ru", "mixed"],
  podcast: ["wer", "itErrors", "numericErrors"],
}

const wer = new Set(["wer", "ru", "mixed", "prose", "numberPhrases", "hyphenated"])
const higherIsBetter = new Set(["numbers", "terms", "ruTerms", "enTerms", "itExact"])

function numericValue(value) {
  if (Number.isFinite(value)) return value
  if (typeof value !== "string") return undefined
  const [correct, total] = value.split("/").map(Number)
  const fraction = correct / total
  return Number.isFinite(fraction) ? fraction : undefined
}

export const groups = Object.entries(reports).map(([id, report]) => ({
  id,
  count: report.rows.length,
  columns: report.columns.map((metric, index) => {
    const columnId = `${id}-${metric}`
    const ascending = !higherIsBetter.has(metric)
    const measured = report.rows.map(([name, ...values]) => [name, values[index], numericValue(values[index])])
      .filter(([, , value]) => value !== undefined)
    const values = new Map(measured.map(([name, value]) => [name, value]))
    const numbers = new Map(measured.map(([name, , value]) => [name, value]))
    const ordered = [...numbers].sort((a, b) => (a[1] - b[1]) * (ascending ? 1 : -1))
    let rank = 0
    const ranks = new Map(ordered.map(([name, value], position) => {
      if (value !== ordered[position - 1]?.[1]) rank = position + 1
      return [name, rank]
    }))
    return {
      id: columnId, group: id, metric, ascending, values, numbers, ranks,
      percent: wer.has(metric), primary: overview[id]?.includes(metric) ?? false,
      precision: metric === "rtf" ? (id === "server" ? 3 : 4) : metric.startsWith("elapsed") ? 2 : 0,
    }
  }),
}))

export const columns = groups.flatMap(group => group.columns)
export const models = [...new Set(columns.flatMap(column => [...column.values.keys()]))]
export const defaultSort = { column: "human-mixed", ascending: true }
export const overviewGroups = groups.map(group => ({
  ...group, columns: group.columns.filter(column => column.primary),
})).filter(group => group.columns.length)

function strongestResult(model) {
  let best
  for (const column of columns) {
    const rank = column.ranks.get(model)
    if (rank === undefined) continue
    const main = column.primary || column.id === "server-rtf"
    if (!best || (main && !best.main) || (main === best.main && rank < best.rank)) {
      best = { column, rank, main }
    }
  }
  return best
}

export const modelResults = new Map(models.map((name, index) => [name, { index, best: strongestResult(name) }]))

export function rankModels(sort) {
  const { numbers } = columns.find(column => column.id === sort.column)
  return [...models].sort((a, b) => {
    const left = numbers.get(a)
    const right = numbers.get(b)
    if (left === undefined) return right === undefined ? 0 : 1
    if (right === undefined) return -1
    return (left - right) * (sort.ascending ? 1 : -1)
  })
}
