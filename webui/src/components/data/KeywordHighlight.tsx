export function KeywordHighlight({ value, query }: { value: string; query: string }) {
  const terms = [...new Set(query.split(/\s+/).filter(Boolean))].sort((a, b) => b.length - a.length)
  if (!terms.length) return <>{value}</>
  const pattern = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  return <>{value.split(new RegExp(`(${pattern})`, 'gi')).map((part, i) => terms.some((term) => term.toLowerCase() === part.toLowerCase())
    ? <mark key={i} className="rounded-sm bg-cyber-neon-cyan/20 px-0.5 font-semibold text-inherit">{part}</mark>
    : part)}</>
}
