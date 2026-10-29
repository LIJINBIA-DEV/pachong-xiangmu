import { useQuery } from '@tanstack/react-query'
import { Square } from 'lucide-react'
import { dataApi } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import { Button } from '@/components/ui/button'
import { CollectionMetricLabel } from '@/components/ui/CollectionMetricLabel'
import playIcon from '@/assets/config/play.svg'

export function CollectionProgressBar({ active, busy, starting, stopping, startDisabled, onStart, onStop }: {
  active: boolean; busy: boolean; starting: boolean; stopping: boolean; startDisabled: boolean; onStart: () => void; onStop: () => void
}) {
  const status = useCrawlerStore(state => state.status)
  const stage = useCrawlerStore(state => state.stage)
  const startedAt = useCrawlerStore(state => state.startedAt)
  const query = useQuery({ queryKey: ['collectionProgress', status, startedAt], enabled: active,
    queryFn: async () => (await dataApi.getCollectionProgress()).data, retry: 1,
    refetchInterval: active && busy ? 2000 : false })
  const incoming = query.data
  // A new start can precede the status poll. Never show the previous run as current progress.
  const data = !busy || incoming && ['running', 'stopping'].includes(incoming.status) && incoming.started_at === startedAt ? incoming : undefined
  const prepared = !!data?.task_id
  const waiting = busy && (starting || stage !== 'running' && status !== 'stopping')
  const percent = waiting || !prepared ? null : data.percent
  const title = stopping || status === 'stopping' ? '正在停止，等待当前操作保存' : waiting ? stage === 'waiting_login' ? '等待登录，尚未开始采集' : '正在准备采集' : busy ? '正在采集' : data?.run_status === 'failed' ? '采集失败，已保存现有数据' : data?.run_status === 'stopped' ? '采集已停止' : '最近一次采集已结束'
  return <div className="config-actions">
    {(busy || prepared) && <section className="collection-progress-panel" aria-label="采集进度">
      <div className="collection-progress-heading"><strong role="status">{title}</strong>{busy && <Button type="button" size="sm" className="config-stop" disabled={starting || stopping || status === 'stopping'} onClick={onStop}><Square size={14} />{stopping || status === 'stopping' ? '正在停止…' : '停止采集'}</Button>}</div>
      <div className="collection-progress-track" role="progressbar" aria-label="自动筛选通过目标进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
        <span style={{ width: `${percent ?? 0}%` }} /><strong>{percent == null ? waiting ? '登录验证通过后开始统计进度' : '正在读取实际进度…' : `目标完成进度 ${percent}% · 自动筛选通过 ${data?.qualified ?? 0} / 目标 ${data?.target ?? '—'} 帖`}</strong>
      </div>
      {prepared && !waiting && <div className="collection-progress-stats">
        {([['checked', data.checked], ['saved', data.saved], ['qualified', data.qualified]] as const).map(([metric, value]) => <span key={metric}><CollectionMetricLabel metric={metric} /><b>{value}</b><small>帖</small></span>)}
        {[['目标帖子数', data.target ?? '—', '帖'], ['已采评论', data.comments, '条'], ['已下载图片', data.images, '张']].map(([label, value, unit]) => <span key={label}><small>{label}</small><b>{value}</b><small>{unit}</small></span>)}
      </div>}
      {prepared && !waiting && <p>{data.current_keyword ? `当前主题：${data.current_keyword} · ` : ''}已完成主题 {data.completed_topics} / {data.total_topics} · 自动筛选通过的直接保留，不确定的交由人工复核。</p>}
      {query.isError && <p role="status">进度暂时读取失败，采集仍按后台状态进行；可到控制台查看输出。</p>}
    </section>}
    {!busy && <Button type="button" disabled={startDisabled} className="config-primary" onClick={onStart}><img src={playIcon} alt="" />开始爬虫</Button>}
  </div>
}
