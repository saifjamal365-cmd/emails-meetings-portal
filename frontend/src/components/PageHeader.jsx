// The top of every page: the title, one plain sentence that says what the page is for,
// and a few real examples. `bar` = the full-height pages (inbox, meetings), where the header
// is a strip across the top; `children` = the page's buttons, on the right.
export default function PageHeader({ title, description, examples = [], meta, bar = false, children }) {
  return (
    <header
      className={`flex flex-wrap items-start gap-x-6 gap-y-3 ${
        bar ? 'border-b border-slate-200 bg-surface px-6 py-4' : 'mb-6'
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <h2 className={`font-semibold tracking-tight text-slate-900 ${bar ? 'text-xl' : 'text-2xl'}`}>{title}</h2>
          {meta && <span className="tabular text-sm text-slate-500">{meta}</span>}
        </div>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>}
        {examples.length > 0 && (
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            <span>For example:</span>
            {examples.map((example) => (
              <span key={example} className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-700">
                {example}
              </span>
            ))}
          </p>
        )}
      </div>
      {children && <div className="flex flex-wrap items-center gap-3">{children}</div>}
    </header>
  )
}
