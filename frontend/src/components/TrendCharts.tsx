import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type TrendMonth, type TrendsResponse } from '../api'
import { formatMoney, formatMoneyCompact, formatMonthUTC } from '../format'

type Key = 'new_customers' | 'churned' | 'take_home'

interface Series {
  key: Key
  label: string
  short: string // for the direct label at the line's end
  color: string // a --series-* token: identity lives on the mark, never the text
}

const NEW: Series = { key: 'new_customers', label: 'New customers', short: 'new', color: 'var(--series-1)' }
const CHURNED: Series = { key: 'churned', label: 'Churned', short: 'churned', color: 'var(--series-2)' }
const TAKE_HOME: Series = { key: 'take_home', label: 'Take-home', short: '', color: 'var(--series-3)' }

// One row per month. Each series is split in two: complete months on a solid line, and the
// last complete month joined to the month in progress on a dashed one, so a partial month
// doesn't read as a drop.
type Row = TrendMonth & { label: string } & Partial<Record<`${Key}_solid` | `${Key}_partial`, number | null>>

function rows(months: TrendMonth[], series: Series[]): Row[] {
  const last = months.length - 1
  const inProgress = months[last]?.partial ?? false
  return months.map((m, i) => {
    const row: Row = { ...m, label: formatMonthUTC(m.start, 'short') }
    for (const s of series) {
      row[`${s.key}_solid`] = inProgress && i === last ? null : m[s.key]
      row[`${s.key}_partial`] = inProgress && i >= last - 1 ? m[s.key] : null
    }
    return row
  })
}

/** The month-over-month charts that lead the Overview: new vs churned customers, and take-home. */
export function TrendCharts() {
  const q = useQuery({ queryKey: ['trends'], queryFn: api.trends })
  return (
    <div className="cards trends">
      <ChartCard title="New vs churned customers" query={q}>
        {q.data && <CustomersChart data={q.data} />}
      </ChartCard>
      <ChartCard title="Monthly take-home" query={q}>
        {q.data && <TakeHomeChart data={q.data} />}
      </ChartCard>
    </div>
  )
}

function ChartCard({
  title,
  query,
  children,
}: {
  title: string
  query: { isPending: boolean; isError: boolean; error: Error | null }
  children: ReactNode
}) {
  return (
    <section className="card chart-card">
      <header className="card-header">
        <h2>{title}</h2>
        <span className="muted">Past 12 months</span>
      </header>
      {query.isPending && <p className="muted">Loading…</p>}
      {query.isError && <p className="error">{query.error?.message}</p>}
      {children}
    </section>
  )
}

/** The last complete month and the one before it: the comparison the headline makes. */
function lastTwo(months: TrendMonth[]): [TrendMonth | undefined, TrendMonth | undefined] {
  const complete = months.filter((m) => !m.partial)
  return [complete.at(-1), complete.at(-2)]
}

function CustomersChart({ data }: { data: TrendsResponse }) {
  const series = data.churn_available ? [NEW, CHURNED] : [NEW]
  const [last] = lastTwo(data.months)
  const net = last ? last.new_customers - last.churned : 0
  return (
    <>
      {last && (
        <div className="card-stat">
          <span className="stat-value">{data.churn_available ? `${net > 0 ? '+' : ''}${net}` : last.new_customers}</span>
          <span className="muted">
            {data.churn_available
              ? `net in ${formatMonthUTC(last.start)}: ${last.new_customers} new, ${last.churned} churned`
              : `new customers in ${formatMonthUTC(last.start)}`}
          </span>
        </div>
      )}
      <Legend series={series} />
      <Chart data={data} series={series} format={(v) => v.toLocaleString()} />
      {!data.churn_available && (
        <p className="muted chart-note">Churn needs Read access to Subscriptions on the Stripe key.</p>
      )}
    </>
  )
}

function TakeHomeChart({ data }: { data: TrendsResponse }) {
  const cur = data.reporting_currency
  const [last, prior] = lastTwo(data.months)
  const current = data.months.at(-1)
  return (
    <>
      {last && (
        <div className="card-stat">
          <span className="stat-value">{formatMoney(last.take_home, cur)}</span>
          <span className="muted">in {formatMonthUTC(last.start)}</span>
          {prior && <Delta now={last.take_home} before={prior.take_home} vs={formatMonthUTC(prior.start, 'short')} />}
        </div>
      )}
      {current?.partial && <MonthSoFarKey />}
      <Chart
        data={data}
        series={[TAKE_HOME]}
        format={(v) => formatMoney(v, cur)}
        formatTick={(v) => formatMoneyCompact(v, cur)}
      />
      {data.unconverted_count > 0 && (
        <p className="muted chart-note">
          {data.unconverted_count} payment{data.unconverted_count === 1 ? '' : 's'} left out: no exchange rate.
        </p>
      )}
    </>
  )
}

/** Month-over-month change: an arrow and sign carry the direction, so it never relies on color. */
function Delta({ now, before, vs }: { now: number; before: number; vs: string }) {
  if (before <= 0) return null
  const pct = Math.round(((now - before) / before) * 100)
  const tone = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
  const arrow = pct > 0 ? '▲' : pct < 0 ? '▼' : '■'
  return (
    <span className={`delta ${tone}`}>
      {arrow} {pct > 0 ? '+' : ''}
      {pct}% <span className="muted">vs {vs}</span>
    </span>
  )
}

function Legend({ series }: { series: Series[] }) {
  return (
    <div className="chart-legend">
      {series.map((s) => (
        <span key={s.key}>
          <span className="line-key" style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
      <MonthSoFarKey inline />
    </div>
  )
}

function MonthSoFarKey({ inline = false }: { inline?: boolean }) {
  const key = (
    <span>
      <span className="line-key dashed" />
      This month so far
    </span>
  )
  return inline ? key : <div className="chart-legend">{key}</div>
}

function Chart({
  data,
  series,
  format,
  formatTick = format,
}: {
  data: TrendsResponse
  series: Series[]
  format: (v: number) => string
  formatTick?: (v: number) => string
}) {
  const chartRows = rows(data.months, series)
  const last = chartRows.length - 1
  // Direct end-labels only when they can't collide; otherwise the legend and tooltip carry identity.
  const ends = series.map((s) => chartRows[last]?.[s.key] ?? 0)
  const spread = Math.max(...ends) - Math.min(...ends)
  const showEndLabels = series.length === 1 || spread >= 0.15 * Math.max(1, ...chartRows.flatMap((r) => series.map((s) => r[s.key])))

  const endLabel = (s: Series) =>
    function EndLabel(p: { x?: number | string; y?: number | string; index?: number; value?: unknown }) {
      if (!showEndLabels || p.index !== last || typeof p.value !== 'number') return null
      return (
        <text x={Number(p.x) + 8} y={Number(p.y)} dy="0.35em" className="chart-end-label">
          {series.length > 1 ? `${p.value.toLocaleString()} ${s.short}` : formatTick(p.value)}
        </text>
      )
    }

  return (
    <>
      <div className="chart" role="img" aria-label={`${series.map((s) => s.label).join(' and ')} by month`}>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartRows} margin={{ top: 12, right: showEndLabels ? 72 : 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={{ stroke: 'var(--axis)' }}
              tick={{ fill: 'var(--muted)', fontSize: 12 }}
              interval="preserveStartEnd"
              minTickGap={8}
            />
            <YAxis
              allowDecimals={false}
              tickLine={false}
              axisLine={false}
              tick={{ fill: 'var(--muted)', fontSize: 12 }}
              tickFormatter={formatTick}
              width={56}
            />
            <Tooltip
              cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }}
              isAnimationActive={false}
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <ChartTooltip row={payload[0].payload as Row} series={series} format={format} />
                ) : null
              }
            />
            {series.flatMap((s) => [
              <Line
                key={`${s.key}-solid`}
                dataKey={`${s.key}_solid`}
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                dot={false}
                activeDot={{ r: 4, fill: s.color, stroke: 'var(--surface)', strokeWidth: 2 }}
                label={endLabel(s)}
                isAnimationActive={false}
              />,
              <Line
                key={`${s.key}-partial`}
                dataKey={`${s.key}_partial`}
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray="4 4"
                strokeLinecap="round"
                dot={false}
                activeDot={{ r: 4, fill: s.color, stroke: 'var(--surface)', strokeWidth: 2 }}
                label={endLabel(s)}
                legendType="none"
                isAnimationActive={false}
              />,
            ])}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="chart-table">
        <summary>View as table</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Month</th>
                {series.map((s) => (
                  <th key={s.key} className="right">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...data.months].reverse().map((m) => (
                <tr key={m.start}>
                  <td>
                    {formatMonthUTC(m.start)}
                    {m.partial && <span className="muted"> (so far)</span>}
                  </td>
                  {series.map((s) => (
                    <td key={s.key} className="right num">
                      {format(m[s.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  )
}

/** Every series at the hovered month; the value leads, the series name follows. */
function ChartTooltip({ row, series, format }: { row: Row; series: Series[]; format: (v: number) => string }) {
  return (
    <div className="chart-tooltip">
      <div className="muted">
        {formatMonthUTC(row.start)}
        {row.partial && ' (so far)'}
      </div>
      {series.map((s) => (
        <div key={s.key} className="chart-tooltip-row">
          <span className="line-key" style={{ background: s.color }} />
          <strong className="num">{format(row[s.key])}</strong>
          <span className="muted">{s.label}</span>
        </div>
      ))}
    </div>
  )
}
