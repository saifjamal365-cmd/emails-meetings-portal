// Shows text with the given words marked (the meeting keywords found in an email).
export default function Highlight({ text, words }) {
  const clean = words.filter((w) => w && w.trim().length > 1)
  if (!clean.length) return text

  const escaped = clean.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const parts = text.split(new RegExp(`(${escaped.join('|')})`, 'gi'))
  const lower = clean.map((w) => w.toLowerCase())
  return parts.map((part, i) =>
    lower.includes(part.toLowerCase()) ? (
      <mark key={i} className="rounded bg-yellow-200 px-0.5">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}
