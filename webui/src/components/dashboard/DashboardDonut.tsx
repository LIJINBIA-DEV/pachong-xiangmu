import { useState } from 'react'
import { DashboardTooltip, useDashboardHover } from './DashboardTooltip'
import type { ImageState } from '@/types/dashboard'

export function DashboardDonut({ total, segments, onOpen, onFilter }: {
  total: number; segments: { key: ImageState; label: string; color: string; value: number }[]
  onOpen: () => void; onFilter: (state: ImageState) => void
}) {
  const { anchor, setAnchor, hide } = useDashboardHover()
  const [hovered, setHovered] = useState<ImageState | null>(null)
  const active = anchor ? segments.find((segment) => segment.key === hovered) : undefined
  const clear = () => { hide(); setHovered(null) }
  let offset = 0
  return <><button className="dashboard-donut-button" aria-label="查看图片识别状态明细" onClick={onOpen} onPointerLeave={clear} onBlur={clear}>
    <svg viewBox="0 0 536 320" role="img" aria-label="图片识别状态分布环图" onPointerMove={(event) => {
      if (event.pointerType === 'touch' || !total) return
      const matrix = event.currentTarget.getScreenCTM()
      if (!matrix) return
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
      const x = point.x - 268, y = point.y - 167, radius = Math.hypot(x, y)
      if (radius < 92 || radius > 134) { clear(); return }
      const angle = (Math.atan2(y, x) + Math.PI / 2 + Math.PI * 2) % (Math.PI * 2) / (Math.PI * 2)
      let boundary = 0
      const segment = segments.find((item) => { boundary += item.value / total; return angle < boundary && item.value > 0 })
      if (segment) { setHovered(segment.key); setAnchor({ x: event.clientX, y: event.clientY }) } else clear()
    }}>
      <circle cx="268" cy="167" r="112" fill="none" stroke="#f0f0f0" strokeWidth="32" />
      {segments.map((item) => {
        const length = item.value / Math.max(1, total) * 100, previous = offset
        offset += length
        return <circle key={item.key} className="dashboard-donut-segment" data-active={active?.key === item.key ? 'true' : undefined}
          cx="268" cy="167" r="112" fill="none" stroke={item.color} strokeWidth={active?.key === item.key ? 38 : 32}
          opacity={active && active.key !== item.key ? .45 : 1} pathLength="100" strokeDasharray={`${length} ${100 - length}`} strokeDashoffset={-previous} transform="rotate(-90 268 167)"
          onClick={(event) => { event.stopPropagation(); onFilter(active?.key || item.key); clear() }} />
      })}
      <text x="268" y="155" textAnchor="middle" fill="#8c8c8c" fontSize="14">采集图片</text><text x="268" y="193" textAnchor="middle" fill="#262626" fontSize="30">{total}</text>
    </svg>
  </button><DashboardTooltip anchor={active ? anchor : null}>{active && <><div className="dashboard-tooltip-title">模型识别状态</div><div className="dashboard-tooltip-row"><i style={{ background: active.color }} /><span>{active.label}</span><strong>{active.value} 张</strong></div><div className="dashboard-tooltip-row"><span>占已下载图片</span><strong>{total ? (active.value / total * 100).toFixed(1) : '0'}%</strong></div></>}</DashboardTooltip></>
}
