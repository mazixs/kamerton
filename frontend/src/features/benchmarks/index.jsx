import { useCallback, useEffect, useId, useRef, useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"
import { useConsole } from "@/app/use-console"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card"
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

import { columns, defaultSort, groups, modelResults, overviewGroups, rankModels } from "./leaderboard"
import "./benchmarks.css"

const supportsInvoker = typeof HTMLButtonElement !== "undefined" && "commandForElement" in HTMLButtonElement.prototype
const shortGroups = new Set(["human", "server"])
const shortMetrics = new Set(["ru", "mixed", "wer", "itErrors", "numericErrors"])

function metricLabel(t, metric) {
  return t(`benchmarks.${shortMetrics.has(metric) ? "shortMetric" : "metric"}.${metric}`)
}

export function Benchmarks() {
  const { t, lang } = useConsole()
  const tableId = useId()
  const table = useRef(null)
  const [expanded, setExpanded] = useState(false)
  const [sort, setSort] = useState(defaultSort)
  const visibleGroups = expanded ? groups : overviewGroups
  const columnCount = visibleGroups.reduce((total, group) => total + group.columns.length, 0)
  const orderedModels = rankModels(sort)
  const numbers = [0, 2, 3, 4].map(digits => [digits, new Intl.NumberFormat(lang, {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  })])
  const numberFormats = Object.fromEntries(numbers)
  const percent = new Intl.NumberFormat(lang, { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 })

  function format(column, value) {
    if (typeof value !== "number") return value
    return column.percent ? percent.format(value / 100) : numberFormats[column.precision].format(value)
  }

  const sortBy = useCallback(id => {
    const column = columns.find(column => column.id === id)
    if (column) setSort(current => ({
      column: id, ascending: current.column === id ? !current.ascending : column.ascending,
    }))
  }, [])

  useEffect(() => {
    if (!supportsInvoker) return
    const element = table.current
    function handleCommand(event) {
      if (event.command === "--sort") sortBy(event.source?.dataset.metric)
    }
    element.addEventListener("command", handleCommand)
    return () => element.removeEventListener("command", handleCommand)
  }, [sortBy])

  function toggleExpanded() {
    if (expanded && !columns.find(column => column.id === sort.column).primary) setSort(defaultSort)
    if (expanded) table.current.parentElement.scrollLeft = 0
    setExpanded(!expanded)
  }

  const sortedColumn = columns.find(column => column.id === sort.column)
  const SortIcon = sort.ascending ? ChevronUp : ChevronDown

  return (
    <Card className="benchmark-card" data-expanded={expanded || undefined}>
      <CardHeader className="benchmark-toolbar">
        <CardDescription id="benchmark-method">{t("benchmarks.legend")}</CardDescription>
        <Button type="button" variant="outline" size="sm" aria-controls={tableId} aria-pressed={expanded} onClick={toggleExpanded}>
          {t("benchmarks.allMetrics")}
        </Button>
      </CardHeader>
      <CardContent className="benchmark-content">
        <p role="status" className="sr-only">{t("benchmarks.sortedBy", {
          group: t("benchmarks.group." + sortedColumn.group),
          metric: t("benchmarks.metric." + sortedColumn.metric),
          order: t(sort.ascending ? "benchmarks.ascending" : "benchmarks.descending"),
        })}</p>
        <Table id={tableId} ref={table} aria-describedby="benchmark-method" className="benchmark-table" style={{ "--metric-count": columnCount }}
          containerProps={{ tabIndex: 0, role: "region", "aria-label": t("benchmarks.results"), className: "benchmark-overflow" }}>
          <TableCaption className="sr-only">{t("benchmarks.leaderboard")}</TableCaption>
          <colgroup><col className="benchmark-model-width" /></colgroup>
          {visibleGroups.map(group => (
            <colgroup key={group.id}>{group.columns.map(column => <col key={column.id} className="benchmark-metric-width" />)}</colgroup>
          ))}
          <TableHeader>
            <TableRow>
              <TableHead rowSpan={2} scope="col" data-model-column="">{t("models.model")}</TableHead>
              {visibleGroups.map(group => (
                <TableHead key={group.id} id={`${tableId}-${group.id}`} colSpan={group.columns.length} scope="colgroup" data-group-start="">
                  {t("benchmarks.group." + group.id)}
                </TableHead>
              ))}
            </TableRow>
            <TableRow>
              {visibleGroups.flatMap(group => group.columns.map((column, position) => (
                <TableHead key={column.id} id={`${tableId}-${column.id}`} scope="col" data-group-start={position === 0 ? "" : undefined}
                  aria-sort={sort.column === column.id ? (sort.ascending ? "ascending" : "descending") : undefined}>
                  <Button type="button" variant="ghost" size="xs" data-metric={column.id} aria-label={t("benchmarks.metric." + column.metric)}
                    commandfor={supportsInvoker ? tableId : undefined} command={supportsInvoker ? "--sort" : undefined}
                    onClick={supportsInvoker ? undefined : () => sortBy(column.id)}>
                    <span>{metricLabel(t, column.metric)}</span>
                    <span aria-hidden="true" className="benchmark-sort-icon">
                      {sort.column === column.id ? <SortIcon size={12} /> : column.ascending ? "↓" : "↑"}
                    </span>
                  </Button>
                </TableHead>
              )))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {orderedModels.map(name => {
              const { index, best } = modelResults.get(name)
              const modelId = `${tableId}-model-${index}`
              return (
                <TableRow key={name}>
                  <TableHead scope="row" id={modelId} data-model-column="">
                    {name.split(/(RNN-T|T-One)/).map((part, position) => position % 2
                      ? <span className="benchmark-model-token" key={position}>{part}</span>
                      : part)}
                    <span className="benchmark-best" data-best-rank={best.rank}>
                      {t("benchmarks.modelBest", {
                        rank: best.rank, total: best.column.ranks.size,
                        group: t(`benchmarks.${shortGroups.has(best.column.group) ? "shortGroup" : "group"}.${best.column.group}`),
                        metric: metricLabel(t, best.column.metric),
                        value: format(best.column, best.column.values.get(name)),
                      })}
                    </span>
                  </TableHead>
                  {visibleGroups.flatMap(group => group.columns.map((column, position) => {
                    const rank = column.ranks.get(name)
                    const value = column.values.get(name)
                    return (
                      <TableCell key={column.id} headers={`${modelId} ${tableId}-${group.id} ${tableId}-${column.id}`}
                        data-metric={column.id} data-rank={rank} data-group-start={position === 0 ? "" : undefined}>
                        {value === undefined ? (
                          <><span className="benchmark-missing" aria-hidden="true">-</span><span className="sr-only">{t("benchmarks.missing")}</span></>
                        ) : (
                          <span className="benchmark-value">
                            {rank <= 3 && <>
                              <Badge variant={rank === 1 ? "default" : "secondary"} aria-hidden="true" className="benchmark-rank"><span>{rank}</span></Badge>
                              <span className="sr-only">{t("benchmarks.place", { rank, total: column.ranks.size })}</span>
                            </>}
                            {rank === 1 ? <strong className="benchmark-number">{format(column, value)}</strong> : <span className="benchmark-number">{format(column, value)}</span>}
                          </span>
                        )}
                      </TableCell>
                    )
                  }))}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
        <details className="benchmark-methods">
          <summary>{t("benchmarks.methods")}</summary>
          <dl>
            {groups.map(group => (
              <div key={group.id}>
                <dt>{t("benchmarks.set." + group.id)}</dt>
                <dd>{t("benchmarks.method." + group.id, { models: group.count })}</dd>
              </div>
            ))}
          </dl>
        </details>
      </CardContent>
    </Card>
  )
}
