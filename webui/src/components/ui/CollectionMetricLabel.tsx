import { Info } from 'lucide-react'
import { DashboardHint } from '@/components/dashboard/DashboardTooltip'

export const collectionMetrics = {
  checked: {
    label: '已处理候选帖',
    help: '已进入本轮处理或筛选的候选帖子数，包含通过、排除、待复核和处理中记录。不是最终通过数，也不等于 Jev 调用次数。',
  },
  saved: {
    label: '已记录帖子',
    help: '已写入本机文件、当前能够读取的帖子记录数，包含通过、待复核和排除记录。已记录不代表筛选通过；处理中记录可能尚未计入。',
  },
  qualified: {
    label: '自动筛选通过',
    help: '符合自动采集与筛选规则、计入目标的帖子数。开启语义筛选时结合所选模型判断；关闭时按普通采集规则计数。仍需人工审核，不代表人工已通过。',
  },
} as const

export function CollectionMetricLabel({ metric }: { metric: keyof typeof collectionMetrics }) {
  const { label, help } = collectionMetrics[metric]
  return <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs">
    {label}<DashboardHint text={help}><button type="button" aria-label={`${label}说明`}
      className="inline-flex shrink-0 items-center justify-center rounded-sm text-cyber-text-muted hover:text-cyber-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-500">
      <Info size={13} aria-hidden="true" />
    </button></DashboardHint>
  </span>
}
