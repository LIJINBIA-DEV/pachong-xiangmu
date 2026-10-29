import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowDownToLine, ArrowUpRight, CheckCheck, CircleHelp, Clock3, Database, FileText, Image, Layers3, ListFilter, MessageSquare, RefreshCw, Search, ShieldCheck, Sparkles, TriangleAlert } from 'lucide-react'
import { dataApi } from '@/lib/api'
import type { OverviewPeriod, OverviewTask } from '@/types/dashboard'
import { DashboardHint } from './DashboardTooltip'
import { CollectionTrend, OutcomeRing, TaskBars, dateLabel } from './OverviewCharts'
import './DashboardPage.css'

const periods: { id: OverviewPeriod; label: string }[] = [{ id: 'today', label: '今日' }, { id: 'week', label: '本周' }, { id: 'month', label: '本月' }, { id: 'year', label: '本年' }, { id: 'all', label: '全部' }]
const platformNames: Record<string, string> = { xhs: '小红书', wb: '微博', dy: '抖音', ks: '快手', bili: '哔哩哔哩', tieba: '百度贴吧', zhihu: '知乎', other: '其他平台' }
const statusNames: Record<string, string> = { completed: '已完成', stopped: '已停止', failed: '失败', error: '失败', running: '采集中', starting: '准备中', interrupted: '已中断', historical: '历史记录' }
const warningNames: Record<string, string> = { missing_files: '个原始文件缺失', unreadable_files: '个文件暂时无法读取', unreadable_runs: '条采集轮次记录无法读取', unreadable_tasks: '条任务记录无法读取', unreadable_reviews: '个任务的人工结论暂时无法读取', estimated_round_times: '次历史采集使用文件名或文件时间估算', unknown_round_times: '次采集缺少时间，仅计入“全部”' }
const n = (value: number) => value.toLocaleString('zh-CN')
const time = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '时间未记录'
function duration(value: number | null) { return value === null ? '时长未记录' : value < 60 ? `${value} 秒` : value < 3600 ? `${Math.floor(value / 60)} 分 ${value % 60} 秒` : `${Math.floor(value / 3600)} 小时 ${Math.floor(value % 3600 / 60)} 分` }
function Info({ children, label = '统计说明' }: { children: ReactNode; label?: string }) { return <DashboardHint text={children}><button className="ov-help" aria-label={label}><CircleHelp size={14} /></button></DashboardHint> }
function AnimatedNumber({ value }: { value: number }) {
  const [shown, setShown] = useState(value)
  const current = useRef(value)
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (media.matches) { current.current = value; setShown(value); return }
    let frame = 0
    const start = performance.now(), from = current.current
    const step = (at: number) => { const progress = Math.min(1, (at - start) / 650); const next = Math.round(from + (value - from) * (1 - (1 - progress) ** 3)); current.current = next; setShown(next); if (progress < 1) frame = requestAnimationFrame(step) }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [value])
  return <span aria-label={n(value)}>{n(shown)}</span>
}
function Metric({ title, value, unit, icon, hint, accent, index }: { title: string; value: number; unit: string; icon: ReactNode; hint: string; accent: string; index: number }) {
  return <section className="ov-metric ov-enter" style={{ '--ov-accent': accent, '--ov-delay': `${index * 45}ms` } as CSSProperties}><div className="ov-metric-top"><span className="ov-metric-icon">{icon}</span><Info label={`${title}说明`}>{hint}</Info></div><div className="ov-metric-title">{title}</div><div className="ov-metric-number"><AnimatedNumber value={value} /><span>{unit}</span></div></section>
}
function PanelHeading({ title, caption, children }: { title: string; caption?: string; children?: ReactNode }) { return <header className="ov-panel-heading"><div><h2>{title}</h2>{caption && <p>{caption}</p>}</div>{children}</header> }

export function DashboardPage({ active, onReview, onData }: { active: boolean; onReview: (file: string | null) => void; onData: (file: string) => void }) {
  const [period, setPeriod] = useState<OverviewPeriod>('week')
  const [task, setTask] = useState('')
  const [platform, setPlatform] = useState('')
  const [customOpen, setCustomOpen] = useState(false)
  const [custom, setCustom] = useState({ start: '', end: '' })
  const [range, setRange] = useState<{ start?: string; end?: string }>({})
  const [tableSearch, setTableSearch] = useState('')
  const [page, setPage] = useState(0)
  const [help, setHelp] = useState(false)
  const query = useQuery({ queryKey: ['dashboard-overview', period, range, task, platform], queryFn: async () => (await dataApi.getDashboardOverview({ period, ...range, task_id: task || undefined, platform: platform || undefined })).data, enabled: active, refetchInterval: active ? 15000 : false, retry: 1, placeholderData: previous => previous })
  const live = useQuery({ queryKey: ['dashboard-live-progress'], queryFn: async () => (await dataApi.getCollectionProgress()).data, enabled: active && !!query.data?.active, refetchInterval: active && query.data?.active ? 5000 : false })
  const data = query.data
  const m = data?.metrics
  useEffect(() => setPage(0), [period, task, platform, tableSearch, range])
  const filtered = data?.tasks.filter(item => `${item.title} ${platformNames[item.platform] || item.platform} ${statusNames[item.status] || item.status}`.includes(tableSearch.trim())) || []
  const shownPage = Math.min(page, Math.max(0, Math.ceil(filtered.length / 8) - 1))
  const table = filtered.slice(shownPage * 8, shownPage * 8 + 8)
  const scopeLabel = periods.find(item => item.id === (data?.range.period || period))?.label || '自定义时间'
  const activePlatforms = [...new Set(data?.task_options.map(item => item.platform) || [])]
  const warningList = Object.entries(data?.warnings || {}).filter(([, count]) => count > 0)
  const selectTask = (id: string) => { setTask(id); setTableSearch('') }
  function applyDates() { if (!custom.start || !custom.end || custom.start > custom.end) return; setRange({ start: `${custom.start}T00:00:00+08:00`, end: `${custom.end}T23:59:59.999+08:00` }); setPeriod('custom'); setCustomOpen(false) }
  function rowActions(item: OverviewTask) { return <div className="ov-row-actions"><button disabled={!item.file} onClick={() => item.file && onData(item.file)}>查看数据<ArrowUpRight size={13} /></button>{item.metrics.review > 0 && <button disabled={!item.file} onClick={() => onReview(item.file)}>去复核</button>}</div> }
  return <div className="overview-page">
    <div className="ov-scroll">
      <header className="ov-heading ov-enter"><h1>仪表盘</h1><div className="ov-heading-actions"><span className="ov-updated">更新于 {data ? time(data.updated_at) : '读取中'}</span><button className="ov-button" onClick={() => setHelp(value => !value)} aria-expanded={help}><CircleHelp size={15} />统计口径</button><button className="ov-button ov-refresh" disabled={query.isFetching} onClick={() => void query.refetch()} aria-label="刷新仪表盘"><RefreshCw className={query.isFetching ? 'ov-spin' : ''} size={16} /></button></div></header>
      <section className="ov-filters ov-enter" aria-label="仪表盘统计范围"><div className="ov-periods">{periods.map(item => <button key={item.id} aria-pressed={period === item.id} onClick={() => { setPeriod(item.id); setRange({}); setCustomOpen(false) }}>{item.label}</button>)}<button aria-pressed={period === 'custom'} aria-expanded={customOpen} onClick={() => setCustomOpen(value => !value)}>自定义</button></div><div className="ov-filter-selects"><label><ListFilter size={14} /><span className="sr-only">统计平台</span><select aria-label="统计平台" value={platform} onChange={event => { setPlatform(event.target.value); setTask('') }}><option value="">全部平台</option>{activePlatforms.map(id => <option key={id} value={id}>{platformNames[id] || id}</option>)}</select></label><label><span className="sr-only">统计任务</span><select aria-label="统计任务" value={task} onChange={event => setTask(event.target.value)}><option value="">全部采集任务</option>{data?.task_options.filter(item => !platform || item.platform === platform).map(item => <option key={item.id} value={item.id}>{item.title} · {time(item.started_at)}</option>)}</select></label></div>
        {customOpen && <form className="ov-custom-dates" onSubmit={event => { event.preventDefault(); applyDates() }}><label>开始日期<input aria-label="统计开始日期" type="date" required value={custom.start} onChange={event => setCustom({ ...custom, start: event.target.value })} /></label><span>至</span><label>结束日期<input aria-label="统计结束日期" type="date" required min={custom.start} value={custom.end} onChange={event => setCustom({ ...custom, end: event.target.value })} /></label><button className="ov-button" disabled={!custom.start || !custom.end || custom.start > custom.end}>应用时间范围</button><small>按北京时间统计</small></form>}
      </section>
      {help && <section className="ov-help-panel"><h2>这些数字如何计算？</h2><p>所有卡片、图表与任务明细使用同一时间范围，按每轮采集的开始时间归属，采用北京时间。默认查看本周全部任务，补采会计为新的一次采集。</p><p>“已记录”是已保存的帖子记录；“已保留”是其中自动通过或人工确认保留的记录；“待复核”是模型无法确定、需要人工判断的记录。未筛选与处理中单独显示。人工结论采用当前最新状态。</p><p>同一任务的采集结果、语义记录和补采重复行会合并；同一帖子出现在不同任务或主题中可形成多条记录，“独立帖子”按平台与帖子编号去重。已检查候选数含未保存的排除候选，因此可能大于已记录数量。</p><p>任务目标以完整任务配置为准，不对多次补采重复累加。AI 报告统计所选任务已生成的报告，不受报告生成日期限制。历史文件缺少运行记录时使用文件名或文件时间估算，未知时长不会显示为零。</p></section>}
      {query.isError && <div className="ov-error" role="alert"><TriangleAlert size={17} /><span>{data ? '刷新失败，暂时展示上次成功读取的数据。' : '仪表盘数据读取失败，请重试。'}</span><button onClick={() => void query.refetch()}>重新读取</button></div>}
      {!data && !query.isError && <div className="ov-loading" role="status"><div className="ov-loading-orbit" /><h2>正在整理采集记录</h2><p>读取任务、筛选结果与人工结论…</p></div>}
      {data && m && <>
        <div className="ov-scope-caption"><span><span className="ov-live-dot" />{scopeLabel} · {data.scope.task_id ? '单个任务' : '全部任务'}<b>{n(m.tasks)} 个任务 / {n(m.rounds)} 次采集</b></span><span>{dateLabel(data.range.start)} — {dateLabel(data.range.end)}<span className="ov-scope-year"> · 北京时间</span>{query.isFetching && <small> 正在更新…</small>}</span></div>
        {data.active && <section className="ov-live"><Activity size={20} /><div><strong>{live.data?.stage === 'waiting_login' ? '等待登录' : '当前采集进行中'}</strong><p>{live.data ? `${live.data.current_keyword || '准备采集'} · 已检查 ${live.data.checked} 帖 · 已记录 ${live.data.saved} 帖 · 筛选通过 ${live.data.qualified} / ${live.data.target ?? '—'} 帖` : '正在读取当前采集进度…'}</p></div><a href="#/config">查看采集进度 <ArrowUpRight size={14} /></a><div className="ov-live-track"><span style={{ width: `${live.data?.percent ?? 0}%` }} /></div></section>}
        <div className="ov-metrics">
          <Metric index={0} title="采集次数" value={m.rounds} unit="次" icon={<Layers3 size={18} />} accent="#4775f5" hint="每启动一轮采集计为一次；同一任务补采会另计一次。失败或停止的轮次也保留记录，历史导出按批次计。" />
          <Metric index={1} title="已检查候选" value={m.checked} unit="帖次" icon={<Search size={18} />} accent="#7b67d9" hint="采集过程实际检查的候选数量。优先使用运行诊断与筛选汇总；缺少完整计数的历史任务按已存记录计算，不推测额外候选。补采再次检查同帖会另计。" />
          <Metric index={2} title="已记录帖子" value={m.recorded} unit="条" icon={<Database size={18} />} accent="#4775f5" hint="已写入采集文件的记录总数，包括保留、待复核、排除等状态；不是全部审核通过。采集结果与语义记录中的同一帖子合并统计。" />
          <Metric index={3} title="已保留帖子" value={m.retained} unit="条" icon={<ShieldCheck size={18} />} accent="#10a693" hint="自动筛选通过或人工明确确认保留的记录；人工排除的记录不计入。自动通过可以直接使用，不要求逐条人工审核。" />
          <Metric index={4} title="待复核帖子" value={m.review} unit="条" icon={<Clock3 size={18} />} accent="#d99b32" hint="语义筛选未能确定是否符合要求的记录，需要到人工审核中决定保留或排除。自动通过、未筛选和处理中不会混入这个数字。" />
          <Metric index={5} title="已采集评论" value={m.comments} unit="条" icon={<MessageSquare size={18} />} accent="#13a0b7" hint="实际保存的评论数量，包含用于补充语义判断的评论。相同任务重复文件中的同一评论只计一次；不同任务中再次采集仍各计一次。" />
        </div>
        {!m.tasks && <section className="ov-no-data"><Database size={28} /><div><h2>这个范围还没有采集记录</h2><p>可切换“全部”查看历史，或到配置页开始一次采集。</p></div><button className="ov-button" onClick={() => { setPeriod('all'); setRange({}) }}>查看全部记录</button></section>}
        <div className="ov-chart-grid">
          <section className="ov-panel ov-enter"><PanelHeading title="采集与筛选趋势"><span className="ov-panel-tag">{data.range.interval === 'hour' ? '每小时' : data.range.interval === 'month' ? '每月' : '每天'}</span></PanelHeading><CollectionTrend points={data.timeline} interval={data.range.interval} /><footer className="ov-panel-note">悬停查看精确数量，点击图例可切换曲线。保留和待复核均包含在已记录中。</footer></section>
          <section className="ov-panel ov-enter"><PanelHeading title="采集任务产出"><Info>每组柱子对比一个任务的已记录与已保留帖子。柱宽固定上限，点击可单独查看任务，悬停可查看完整主题、时间与数量。</Info></PanelHeading><TaskBars tasks={data.tasks} onSelect={selectTask} /></section>
        </div>
        <div className="ov-details-grid">
          <section className="ov-panel ov-enter"><PanelHeading title="帖子处理结果" /><OutcomeRing metrics={m} /><footer className="ov-panel-note">已排除 {n(m.excluded)} 条中，人工确认排除 {n(m.manual_excluded)} 条。未导出的候选不计入此图。</footer></section>
          <section className="ov-panel ov-enter"><PanelHeading title="评论、媒体与 AI" /><div className="ov-assets"><div><span className="ov-asset-icon"><MessageSquare size={19} /></span><div><span>采集评论</span><strong>{n(m.comments)}<small> 条</small></strong></div><p>已写入采集数据</p></div><div><span className="ov-asset-icon"><Image size={19} /></span><div><span>关联图片</span><strong>{n(m.images)}<small> 张</small></strong></div><p>{n(m.online_images)} 张在线图片{m.missing_images > 0 && ` · ${n(m.missing_images)} 张缺少地址`}</p></div><div><span className="ov-asset-icon"><ArrowDownToLine size={19} /></span><div><span>本地可用图片</span><strong>{n(m.downloaded)}<small> 张</small></strong></div><p>{n(m.download_failed)} 张本地文件异常</p></div><div><span className="ov-asset-icon ov-purple"><Sparkles size={19} /></span><div><span>AI 总结报告</span><strong>{n(m.summary_ready)}<small> 份</small></strong></div><p>在数据管理中查看与生成</p></div></div><footer className="ov-panel-note">AI 总结报告按所选采集任务统计；图片只记录可用性，不参与语义筛选或自动审核。</footer></section>
        </div>
        <section className="ov-panel ov-task-panel ov-enter"><PanelHeading title="采集任务明细" caption={`${n(m.tasks)} 个任务 · 保留完整采集历史，包括未产出数据的启动记录`}><label className="ov-table-search"><Search size={15} /><input aria-label="搜索采集任务" placeholder="搜索主题、平台或状态" value={tableSearch} onChange={event => setTableSearch(event.target.value)} /></label></PanelHeading><div className="ov-table-scroll"><table><thead><tr><th>采集任务 / 时间</th><th>运行状态</th><th>已检查<Info>检查次数含未保存的候选；历史任务计数可能不完整。</Info></th><th>已记录</th><th>已保留 / 目标<Info>目标是整个任务的配置目标，不是本次时间范围新增目标；保留数量采用当前结论。</Info></th><th>待复核</th><th>评论</th><th>操作</th></tr></thead><tbody>{table.map(item => <tr key={item.id}><td><strong className="ov-task-title" title={item.title}>{item.title}</strong><span>{platformNames[item.platform] || item.platform} · {time(item.started_at)}{item.estimated_time && '（估算）'}</span><small>{item.rounds} 次采集 · {duration(item.duration_seconds)}{item.summaries.ready > 0 && ` · ${item.summaries.ready} 份 AI 报告`}</small></td><td><span className={`ov-status ov-status-${item.status}`}>{statusNames[item.status] || '未知状态'}</span></td><td>{n(item.metrics.checked)}</td><td>{n(item.metrics.recorded)}</td><td><span className="ov-kept-number">{n(item.metrics.retained)}</span><span className="ov-target-number"> / {item.target === null ? '未设定' : n(item.target)}</span></td><td><span className={item.metrics.review ? 'ov-review-number' : 'ov-muted'}>{n(item.metrics.review)}</span></td><td>{n(item.metrics.comments)}</td><td>{rowActions(item)}</td></tr>)}</tbody></table>{!table.length && <div className="ov-chart-empty">{tableSearch ? '没有找到匹配的任务' : '所选范围暂无任务'}</div>}</div><footer className="ov-table-footer"><span>共 {filtered.length} 个任务 · 每页 8 个</span><div><button disabled={shownPage === 0} onClick={() => setPage(shownPage - 1)}>上一页</button><span>{filtered.length ? shownPage + 1 : 0} / {Math.ceil(filtered.length / 8)}</span><button disabled={(shownPage + 1) * 8 >= filtered.length} onClick={() => setPage(shownPage + 1)}>下一页</button></div></footer></section>
        {warningList.length > 0 && <aside className="ov-data-notes"><TriangleAlert size={16} /><div><strong>历史数据说明</strong><p>{warningList.map(([key, count]) => `${count} ${warningNames[key] || key}`).join('；')}。缺失部分未编造数值，现有数据保持不变。</p></div></aside>}
        <footer className="ov-page-footer"><CheckCheck size={14} />来源：本机任务记录、采集文件与人工审核结论<span><FileText size={13} />按北京时间统计 · 15 秒自动更新</span></footer>
      </>}
    </div>
  </div>
}
