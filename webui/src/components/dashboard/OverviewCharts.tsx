import { useId, useState } from 'react'
import type { OverviewMetrics, OverviewPoint, OverviewTask } from '@/types/dashboard'
import { DashboardTooltip, useDashboardHover } from './DashboardTooltip'

export const series = [
  { key: 'recorded', label: '已记录帖子', color: '#4775f5' },
  { key: 'retained', label: '已保留帖子', color: '#10a693' },
  { key: 'review', label: '待复核帖子', color: '#e5a038' },
] as const
export const statuses = [
  { key: 'retained', label: '已保留', color: '#10a693' },
  { key: 'review', label: '待复核', color: '#e5a038' },
  { key: 'excluded', label: '已排除', color: '#e77b85' },
  { key: 'unfiltered', label: '未筛选', color: '#8796b5' },
  { key: 'processing', label: '处理中', color: '#8a75e7' },
  { key: 'duplicate', label: '重复记录', color: '#b6c2d4' },
] as const
const n = (value: number) => value.toLocaleString('zh-CN')
export function dateLabel(value: string, interval: 'hour' | 'day' | 'month' = 'day') {
  const date = new Date(value)
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', ...(interval === 'hour' ? { hour: '2-digit', minute: '2-digit', hour12: false } : interval === 'month' ? { year: '2-digit', month: 'short' } : { month: 'numeric', day: 'numeric' }) }).format(date)
}

export function CollectionTrend({ points, interval }: { points: OverviewPoint[]; interval: 'hour' | 'day' | 'month' }) {
  const id = useId().replace(/:/g, '')
  const [visible, setVisible] = useState<string[]>(series.map(item => item.key))
  const [selected, setSelected] = useState<number | null>(null)
  const hover = useDashboardHover()
  const width = 740, height = 245, left = 43, right = 20, top = 20, bottom = 36
  const max = Math.max(1, ...points.flatMap(point => series.filter(item => visible.includes(item.key)).map(item => point[item.key])))
  const magnitude = 10 ** Math.floor(Math.log10(max))
  const tick = Math.max(1, Math.ceil(max / 4 / magnitude * 2) * magnitude / 2)
  const ceiling = Math.ceil(max / tick) * tick
  const ticks = Array.from({ length: Math.round(ceiling / tick) + 1 }, (_, index) => index * tick)
  const x = (index: number) => left + (points.length <= 1 ? .5 : index / (points.length - 1)) * (width - left - right)
  const y = (value: number) => height - bottom - value / ceiling * (height - top - bottom)
  const current = selected === null ? null : points[selected]
  const show = (index: number, element: SVGElement) => { setSelected(index); const box = element.getBoundingClientRect(); hover.setAnchor({ x: box.x + box.width / 2, y: box.y + 25 }) }
  return <div className="ov-trend">
    <div className="ov-chart-key">{series.map(item => <button key={item.key} aria-pressed={visible.includes(item.key)} onClick={() => setVisible(previous => previous.includes(item.key) ? previous.length > 1 ? previous.filter(key => key !== item.key) : previous : [...previous, item.key])}><i style={{ background: item.color }} />{item.label}</button>)}<span>单位：帖</span></div>
    <svg viewBox={`0 0 ${width} ${height}`} role="group" aria-label="按采集时间汇总的帖子数量折线图" className="ov-trend-svg" onPointerLeave={() => { setSelected(null); hover.hide() }}>
      <defs>{series.map(item => <linearGradient key={item.key} id={`${id}-${item.key}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={item.color} stopOpacity=".15" /><stop offset="100%" stopColor={item.color} stopOpacity="0" /></linearGradient>)}</defs>
      {ticks.map(value => <g key={value}><line x1={left} x2={width - right} y1={y(value)} y2={y(value)} className="ov-gridline" /><text x={left - 12} y={y(value) + 4} textAnchor="end">{n(value)}</text></g>)}
      {series.filter(item => visible.includes(item.key)).map(item => {
        const path = points.map((point, index) => `${index ? 'L' : 'M'} ${x(index)} ${y(point[item.key])}`).join(' ')
        return <g key={item.key}><path className="ov-chart-area" d={`${path} L ${x(points.length - 1)} ${height - bottom} L ${x(0)} ${height - bottom} Z`} fill={`url(#${id}-${item.key})`} /><path className="ov-chart-line" pathLength="1" d={path} fill="none" stroke={item.color} strokeWidth="2.6" strokeLinejoin="round" strokeLinecap="round" />{points.length < 32 && points.map((point, index) => <circle key={index} cx={x(index)} cy={y(point[item.key])} r="3.5" fill="var(--ov-panel)" stroke={item.color} strokeWidth="2" />)}</g>
      })}
      {points.map((point, index) => <g key={point.at}>
        {(index === 0 || index === points.length - 1 || index % Math.max(1, Math.ceil(points.length / 7)) === 0) && <text x={x(index)} y={height - 10} textAnchor="middle">{dateLabel(point.at, interval)}</text>}
        <rect x={points.length === 1 ? left : Math.max(left, x(index) - (width - left - right) / (points.length - 1) / 2)} y={top} width={points.length === 1 ? width - left - right : (width - left - right) / (points.length - 1) * (index === 0 || index === points.length - 1 ? .5 : 1)} height={height - top - bottom} fill="transparent" tabIndex={0} role="button" aria-label={`${dateLabel(point.at, interval)}，记录${point.recorded}帖，保留${point.retained}帖，待复核${point.review}帖，${point.rounds}次采集`} onFocus={event => show(index, event.currentTarget)} onBlur={() => { setSelected(null); hover.hide() }} onPointerMove={event => { setSelected(index); hover.setAnchor({ x: event.clientX, y: event.clientY }) }} />
      </g>)}
      {current && <g pointerEvents="none"><line x1={x(selected!)} x2={x(selected!)} y1={top} y2={height - bottom} stroke="#91a0bf" strokeDasharray="4 4" />{series.filter(item => visible.includes(item.key)).map(item => <circle key={item.key} cx={x(selected!)} cy={y(current[item.key])} r="5" stroke="white" strokeWidth="2" fill={item.color} />)}</g>}
    </svg>
    <DashboardTooltip anchor={hover.anchor}>{current && <><strong>{new Date(current.at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</strong><p>{current.rounds} 次采集启动</p>{series.map(item => <div className="dashboard-tooltip-row" key={item.key}><i style={{ background: item.color }} />{item.label}<strong>{n(current[item.key])} 帖</strong></div>)}</>}</DashboardTooltip>
  </div>
}

export function TaskBars({ tasks, onSelect }: { tasks: OverviewTask[]; onSelect: (id: string) => void }) {
  const sorted = [...tasks].sort((a, b) => b.metrics.recorded - a.metrics.recorded).slice(0, 6)
  const hover = useDashboardHover()
  const [selected, setSelected] = useState<OverviewTask | null>(null)
  const max = Math.max(1, ...sorted.map(task => task.metrics.recorded))
  const tick = Math.max(1, Math.ceil(max / 4 / 5) * 5)
  const ceiling = Math.ceil(max / tick) * tick
  const width = 420, height = 287, left = 32, right = 8, top = 23, baseline = 222
  const step = (width - left - right) / Math.max(1, sorted.length)
  const bar = Math.min(17, step * .25)
  const y = (value: number) => baseline - value / ceiling * (baseline - top)
  return <div className="ov-columns"><div className="ov-chart-key"><span><i style={{ background: '#b7c9fc' }} />已记录</span><span><i style={{ background: '#4775f5' }} />其中已保留</span><span>单位：帖</span></div>{sorted.length ? <svg className="ov-columns-svg" viewBox={`0 0 ${width} ${height}`} role="group" aria-label="采集任务记录数量与保留数量柱状图" onPointerLeave={hover.hide}>
    {Array.from({ length: Math.round(ceiling / tick) + 1 }, (_, index) => index * tick).map(value => <g key={value}><line className="ov-gridline" x1={left} x2={width - right} y1={y(value)} y2={y(value)} /><text x={left - 9} y={y(value) + 4} textAnchor="end">{value}</text></g>)}
    {sorted.map((task, index) => { const x = left + step * (index + .5); const activate = () => { setSelected(task); onSelect(task.id); hover.hide() }; return <g key={task.id} role="button" tabIndex={0} aria-label={`${task.title}，${task.started_at ? new Date(task.started_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '历史'}，记录${task.metrics.recorded}帖，保留${task.metrics.retained}帖，点击查看此任务`} onClick={activate} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate() } }} onFocus={event => { setSelected(task); const box = event.currentTarget.getBoundingClientRect(); hover.setAnchor({ x: box.x + box.width / 2, y: box.y + 25 }) }} onBlur={hover.hide} onPointerMove={event => { setSelected(task); hover.setAnchor({ x: event.clientX, y: event.clientY }) }}>
      <rect x={x - step * .47} y={top - 10} width={step * .94} height={height - top} fill="transparent" className="ov-column-hit" />
      <rect className="ov-column" x={x - bar - 2} y={y(task.metrics.recorded)} width={bar} height={baseline - y(task.metrics.recorded)} rx="3" fill="#b7c9fc" />
      <rect className="ov-column" x={x + 2} y={y(task.metrics.retained)} width={bar} height={baseline - y(task.metrics.retained)} rx="3" fill="#4775f5" />
      <text className="ov-column-value" x={x - bar / 2 - 2} y={y(task.metrics.recorded) - 7} textAnchor="middle">{task.metrics.recorded}</text>
      <text x={x} y={baseline + 22} textAnchor="middle">{task.title.length > 6 ? task.title.slice(0, 6) + '…' : task.title}</text>
      <text className="ov-column-date" x={x} y={baseline + 40} textAnchor="middle">{task.last_at ? new Date(task.last_at).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }) : '历史记录'}</text>
    </g> })}
  </svg> : <div className="ov-chart-empty">所选范围暂无采集任务</div>}<DashboardTooltip anchor={hover.anchor}>{selected && <><strong>{selected.title}</strong><p>{selected.started_at ? new Date(selected.started_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '历史记录'}</p><div className="dashboard-tooltip-row">已记录<strong>{selected.metrics.recorded} 帖</strong></div><div className="dashboard-tooltip-row">已保留<strong>{selected.metrics.retained} 帖</strong></div><div className="dashboard-tooltip-row">待复核<strong>{selected.metrics.review} 帖</strong></div><p>点击查看此任务</p></>}</DashboardTooltip></div>
}

export function OutcomeRing({ metrics }: { metrics: OverviewMetrics }) {
  const total = metrics.recorded
  let offset = 0
  return <div className="ov-outcomes"><div className="ov-ring-wrap"><svg viewBox="0 0 180 180" role="img" aria-label={`已记录${total}帖，其中保留${metrics.retained}帖，待复核${metrics.review}帖，排除${metrics.excluded}帖`}><circle cx="90" cy="90" r="70" fill="none" stroke="var(--ov-line)" strokeWidth="15" />{statuses.map(item => { const part = total ? metrics[item.key] / total * 100 : 0; const start = offset; offset += part; return part > 0 && <circle className="ov-ring-part" key={item.key} cx="90" cy="90" r="70" pathLength="100" fill="none" stroke={item.color} strokeWidth="15" strokeDasharray={`${part} ${100 - part}`} strokeDashoffset={-start} transform="rotate(-90 90 90)" /> })}</svg><div><strong>{total ? Math.round(metrics.retained / total * 100) : '—'}{total > 0 && <small>%</small>}</strong><span>记录中保留占比</span></div></div><div className="ov-outcome-legend">{statuses.map(item => <div key={item.key}><i style={{ background: item.color }} /><span>{item.label}</span><strong>{n(metrics[item.key])}</strong><small>{total ? (100 * metrics[item.key] / total).toFixed(1) : '0'}%</small></div>)}</div></div>
}
