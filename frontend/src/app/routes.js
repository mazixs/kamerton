export const HOME_PAGE = "dict"

export const navigation = [
  [HOME_PAGE, "compare", "benchmarks", "api"],
  ["models", "settings", "glossary", "status", "journal"],
]

const pages = new Set(navigation.flat())

export function readPage() {
  const hash = location.hash.slice(1)
  return pages.has(hash) ? hash : HOME_PAGE
}

export function setPage(next) {
  if (pages.has(next)) location.hash = next
}
