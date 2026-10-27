import type { TrendPoint } from '@/types/dashboard'
import { useState } from 'react'
import { DashboardTooltip, useDashboardHover } from './DashboardTooltip'

export const dashboardTime = (value: string, date = false) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', ...(date ? { month: '2-digit', day: '2-digit' } : {}), hour: '2-digit', minute: '2-digit', hour12: false })

export function DashboardChart({ points, metric = 'collected', cumulative = false, mini = false }: {
  points: TrendPoint[]; metric?: 'collected' | 'qualified' | 'images'; cumulative?: boolean; mini?: boolean
}) {
  const { anchor, setAnchor, hide } = useDashboardHover()
  const [hovered, setHovered] = useState<number | null>(null)
  const width = mini ? 232 : 816, height = mini ? 20 : 308
  const left = mini ? 0 : 38, bottom = mini ? 20 : 270, top = mini ? 0 : 24
  let total = 0, accepted = 0
  const values = points.map((point) => {
    total += point[metric]; accepted += point.qualified
    return { ...point, value: cumulative ? total : point[metric], accepted: cumulative ? accepted : point.qualified }
  })
  const peak = Math.max(1, ...values.map((point) => Math.max(point.value, cumulative ? point.accepted : 0)))
  const maximum = mini ? peak : Math.ceil(peak / 5) * 5
  const cell = (width - left - 8) / Math.max(1, values.length)
  const barWidth = Math.min(mini ? 8 : 32, cell * .55)
  const y = (value: number) => bottom - value / maximum * (bottom - top)
  const path = (key: 'value' | 'accepted') => values.map((point, index) => `${index ? 'L' : 'M'}${left + (index + .5) * cell},${y(point[key])}`).join(' ')
  const active = anchor && hovered != null ? values[hovered] : undefined
  const metricLabel = metric === 'qualified' ? '自动筛选通过帖子' : metric === 'images' ? '已采集图片' : '已记录帖子'
  const clear = () => { hide(); setHovered(null) }
  return <><svg viewBox={`0 0 ${width} ${height}`} className={mini ? 'dashboard-mini-chart' : 'dashboard-chart'} role="img" aria-label={cumulative ? '当前组合累计采集与初筛趋势' : `${metric === 'qualified' ? '自动筛选通过' : metric === 'images' ? '图片下载' : '采集'}趋势图`}
    tabIndex={values.length ? 0 : undefined} onPointerLeave={clear} onBlur={clear}
    onPointerMove={(event) => {
      if (event.pointerType === 'touch' || !values.length) return
      // SVG preserveAspectRatio may letterbox the plot, especially on narrow screens.
      const matrix = event.currentTarget.getScreenCTM()
      if (!matrix) return
      const local = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
      if (local.x < left || local.x > width - 8 || local.y < top || local.y > bottom) { clear(); return }
      setHovered(Math.min(values.length - 1, Math.max(0, Math.floor((local.x - left) / cell))))
      setAnchor({ x: event.clientX, y: event.clientY })
    }}
    onFocus={(event) => { if (values.length) { const box = event.currentTarget.getBoundingClientRect(); setHovered(0); setAnchor({ x: box.left + 20, y: box.top + box.height / 2 }) } }}
    onKeyDown={(event) => { if (event.key === 'Escape') { clear(); return } if (!values.length || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; event.preventDefault(); const index = event.key === 'Home' ? 0 : event.key === 'End' ? values.length - 1 : Math.max(0, Math.min(values.length - 1, (hovered ?? 0) + (event.key === 'ArrowRight' ? 1 : -1))); setHovered(index); const box = event.currentTarget.getBoundingClientRect(); setAnchor({ x: box.left + (index + .5) / values.length * box.width, y: box.top + box.height / 2 }) }}>
    {!mini && Array.from({ length: 6 }, (_, index) => {
      const value = maximum * index / 5
      return <g key={index}><line x1={left} x2={width - 8} y1={y(value)} y2={y(value)} stroke="#f0f0f0" /><text x="0" y={y(value) + 4} fill="#8c8c8c" fontSize="12">{value}</text></g>
    })}
    {active && hovered != null && <g className="dashboard-chart-guide" pointerEvents="none">{cumulative || (mini && metric === 'qualified') ? <line x1={left + (hovered + .5) * cell} x2={left + (hovered + .5) * cell} y1={top} y2={bottom} stroke="#bfbfbf" strokeDasharray="4 3" /> : <rect x={left + (hovered + .5) * cell - Math.min(cell, barWidth + 20) / 2} y={top} width={Math.min(cell, barWidth + 20)} height={bottom - top} fill="#eef2fa" rx="4" />}</g>}
    {cumulative || (mini && metric === 'qualified') ? <>
      {mini && values.length > 0 && <path d={`${path('value')} L${left + (values.length - .5) * cell},${bottom} L${left + .5 * cell},${bottom} Z`} fill="#d3adf7" />}
      <path d={path('value')} fill="none" stroke={mini ? '#b37feb' : '#1890ff'} strokeWidth={mini ? 2 : 2.5} />
      {cumulative && <path d={path('accepted')} fill="none" stroke="#13c2c2" strokeWidth="2.5" />}
    </> : values.map((point, index) => <g key={point.at}>
      <rect x={left + (index + .5) * cell - barWidth / 2} y={y(point.value)} width={barWidth} height={Math.max(0, bottom - y(point.value))} rx={mini ? 1 : 3} fill="#1890ff" className="dashboard-chart-bar" data-active={active && hovered === index ? 'true' : undefined} />
      {!mini && values.length <= 12 && point.value > 0 && <text x={left + (index + .5) * cell} y={y(point.value) - 8} textAnchor="middle" fill="currentColor" fontSize="12" className="dashboard-chart-value">{point.value}</text>}
    </g>)}
    {active && hovered != null && (cumulative || (mini && metric === 'qualified')) && <g pointerEvents="none"><circle cx={left + (hovered + .5) * cell} cy={y(active.value)} r={mini ? 2 : 4} fill={mini ? '#b37feb' : '#1890ff'} stroke="white" strokeWidth="2" />{cumulative && <circle cx={left + (hovered + .5) * cell} cy={y(active.accepted)} r="4" fill="#13c2c2" stroke="white" strokeWidth="2" />}</g>}
    {!mini && values.map((point, index) => <text key={point.at} x={left + (index + .5) * cell} y="296" textAnchor="middle" fill="#8c8c8c" fontSize="11">{dashboardTime(point.at)}</text>)}
    {!mini && values.every((point) => point.value === 0) && <text x={width / 2} y={height / 2} fill="#8c8c8c" textAnchor="middle" fontSize="14">所选时间内暂无采集记录</text>}
  </svg><DashboardTooltip anchor={active ? anchor : null}><div className="dashboard-tooltip-title">{active ? dashboardTime(active.at, true) : ''}</div>{active && <><div className="dashboard-tooltip-row"><i style={{ background: mini && metric === 'qualified' ? '#b37feb' : '#1890ff' }} /><span>{metricLabel}</span><strong>{active.value}</strong></div>{cumulative && <div className="dashboard-tooltip-row"><i style={{ background: '#13c2c2' }} /><span>自动筛选通过帖子</span><strong>{active.accepted}</strong></div>}</>}</DashboardTooltip></>
}
