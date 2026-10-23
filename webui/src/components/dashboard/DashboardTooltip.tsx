import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export interface TooltipAnchor { x: number; y: number }

export function useDashboardHover() {
  const [anchor, setAnchor] = useState<TooltipAnchor | null>(null)
  useEffect(() => {
    const hide = () => setAnchor(null)
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') hide() }
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    window.addEventListener('blur', hide)
    window.addEventListener('keydown', escape)
    return () => { window.removeEventListener('scroll', hide, true); window.removeEventListener('resize', hide); window.removeEventListener('blur', hide); window.removeEventListener('keydown', escape) }
  }, [])
  return { anchor, setAnchor, hide: () => setAnchor(null) }
}

export function DashboardTooltip({ anchor, children, id, dark = false }: {
  anchor: TooltipAnchor | null; children: ReactNode; id?: string; dark?: boolean
}) {
  const element = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  useLayoutEffect(() => {
    if (!anchor || !element.current) return
    const { width, height } = element.current.getBoundingClientRect()
    setPosition({ left: Math.max(8, Math.min(anchor.x + 12, window.innerWidth - width - 8)),
      top: Math.max(8, anchor.y + height + 20 > window.innerHeight ? anchor.y - height - 12 : anchor.y + 12) })
  }, [anchor, children])
  if (!anchor) return null
  return createPortal(<div ref={element} role="tooltip" id={id} className={`dashboard-tooltip ${dark ? 'dashboard-tooltip-dark' : ''}`} style={position}>{children}</div>, document.body)
}

export function DashboardHint({ text, children }: { text: ReactNode; children: ReactNode }) {
  const { anchor, setAnchor, hide } = useDashboardHover()
  const id = useId()
  return <span className="dashboard-tooltip-anchor" aria-describedby={anchor ? id : undefined}
    onPointerEnter={(event) => { if (event.pointerType !== 'touch') setAnchor({ x: event.clientX, y: event.clientY }) }}
    onPointerLeave={hide} onFocus={(event) => { const box = event.currentTarget.getBoundingClientRect(); setAnchor({ x: box.left + box.width / 2, y: box.bottom }) }}
    onBlur={hide} onClick={hide}>
    {children}<DashboardTooltip id={id} anchor={anchor} dark>{text}</DashboardTooltip>
  </span>
}
