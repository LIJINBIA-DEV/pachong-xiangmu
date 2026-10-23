import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as Dialog from '@radix-ui/react-dialog'
import { dataApi } from '@/lib/api'
import type { DashboardSnapshot, DashboardPeriod, DashboardGroup, ImageState } from '@/types/dashboard'
import { DashboardChart, dashboardTime } from './DashboardChart'
import { DashboardDonut } from './DashboardDonut'
import { DashboardHint } from './DashboardTooltip'
import infoIcon from '@/assets/dashboard/info.svg'
import calendarIcon from '@/assets/dashboard/calendar.svg'
import closeIcon from '@/assets/dashboard/close.svg'
import passIcon from '@/assets/dashboard/legend-pass.svg'
import rejectIcon from '@/assets/dashboard/legend-reject.svg'
import pendingIcon from '@/assets/dashboard/legend-pending.svg'
import failedIcon from '@/assets/dashboard/legend-failed.svg'
import './DashboardPage.css'

const stateLabels = { qualified: '通过', unqualified: '未通过', pending: '待识别', failed: '识别失败' }
const groupLabels = { running: '采集中', completed: '已完成', interrupted: '已中断', pending: '待开始' }
const series = [
  { key: 'qualified', color: '#1890ff', icon: passIcon }, { key: 'unqualified', color: '#fa8c16', icon: rejectIcon },
  { key: 'pending', color: '#b37feb', icon: pendingIcon }, { key: 'failed', color: '#f5222d', icon: failedIcon },
] as const
type Modal = 'info' | 'task' | 'images' | 'recognition' | null
function Progress({ value, green = false }: { value: number; green?: boolean }) {
  return <div className="dashboard-progress" role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${Math.min(100, Math.max(0, value))}%`, background: green ? '#52c41a' : undefined }} /></div>
}
function GroupTable({ groups, detailed = false }: { groups: DashboardGroup[]; detailed?: boolean }) {
  return <div className="dashboard-table-scroll"><table><thead><tr>{!detailed && <th>序号</th>}<th>搜索组合</th><th>采集帖子</th><th>初筛目标{detailed ? '进度' : ''}</th>{detailed && <th>任务状态</th>}</tr></thead>
    <tbody>{groups.map((group, index) => <tr key={group.keyword}>{!detailed && <td>{index + 1}</td>}<td>{group.keyword}</td><td>{group.collected}</td><td>{group.qualified} / {group.target ?? '—'}</td>{detailed && <td className={group.status === 'running' ? 'dashboard-blue' : ''}>{groupLabels[group.status]}</td>}</tr>)}</tbody></table>{!groups.length && <p className="dashboard-empty">暂无搜索组合</p>}</div>
}
function Statistic({ title, description, value, footer, onClick, onInfo, children, badge }: {
  title: string; description: string; value: ReactNode; footer: string; onClick: () => void; onInfo: () => void; children: ReactNode; badge?: string
}) {
  return <section className="dashboard-stat dashboard-card"><header><h2>{title}</h2>{badge && <span className="dashboard-badge">{badge}</span>}</header>
    <div className="dashboard-stat-body"><div className="dashboard-stat-label"><span>{description}</span><DashboardHint text={`${title}：${description}。点击查看详细统计口径。`}><button aria-label={`${title}统计说明`} onClick={onInfo}><img src={infoIcon} alt="" /></button></DashboardHint></div>
      <button className="dashboard-stat-value" onClick={onClick}>{value}</button><div className="dashboard-stat-detail">{children}</div>
      <button className="dashboard-stat-link" onClick={onClick}>{footer} ›</button></div></section>
}

export function DashboardPage({ active, onReview }: { active: boolean; onReview: (file: string | null) => void }) {
  const [period, setPeriod] = useState<DashboardPeriod>('task')
  const [range, setRange] = useState<{ start?: string; end?: string }>({})
  const [custom, setCustom] = useState({ start: '', end: '' })
  const [dateOpen, setDateOpen] = useState(false)
  const [dateError, setDateError] = useState(false)
  const [metric, setMetric] = useState<'collected' | 'qualified'>('collected')
  const [keyword, setKeyword] = useState('')
  const [modal, setModal] = useState<Modal>(null)
  const [imageFilter, setImageFilter] = useState<ImageState | 'all'>('all')
  const [imagePage, setImagePage] = useState(0)
  const query = useQuery({ queryKey: ['dashboard', period, range.start, range.end], queryFn: async () => (await dataApi.getDashboard(period, range.start, range.end)).data,
    enabled: active, refetchInterval: active ? 10000 : false, retry: 1, placeholderData: (previous) => previous })
  const data = query.data
  useEffect(() => { if (data && !data.groups.some((group) => group.keyword === keyword)) setKeyword(data.task.current_keyword || data.groups[0]?.keyword || '') }, [data, keyword])
  const current = data?.groups.find((group) => group.keyword === data.task.current_keyword)
  const selected = data?.groups.find((group) => group.keyword === keyword)
  const percentage = (count: number, target: number | null | undefined) => target ? Math.min(100, 100 * count / target) : 0
  function show(next: Modal) { setImageFilter('all'); setImagePage(0); setModal(next) }
  function setTime(next: DashboardPeriod) { setPeriod(next); setRange({}); setDateOpen(false) }
  const imageCounts = data?.metrics.images
  const filteredImages = data?.images.filter((image) => modal === 'images' || imageFilter === 'all' || image.status === imageFilter) || []
  const pages = Math.ceil(filteredImages.length / 5)
  const shownPage = Math.min(imagePage, Math.max(0, pages - 1))
  const ranked = [...(data?.ranking || [])].sort((left, right) => right[metric] - left[metric])
  const platform = data?.task.platform === 'wb' ? '微博' : data?.task.platform === 'xhs' ? '小红书' : '采集'
  const progress = data ? percentage(data.task.completed_groups, data.task.total_groups) : 0
  return <div className="dashboard-page">
    <header className="dashboard-topbar"><h1>仪表盘</h1><button className="dashboard-task-button" onClick={() => show('task')}>当前任务：{data?.task.file ? `${platform} · 场景图文采集` : '暂无已保存任务'}</button>
      <div className="dashboard-topbar-right"><span>{data ? `最近更新 ${dashboardTime(data.updated_at, true)}` : '正在读取'}</span><span>真实数据</span><button onClick={() => show('info')}>统计说明</button></div></header>
    <div className="dashboard-scroll"><div className="dashboard-content">
      {query.isError && <div role="alert" className="dashboard-alert">统计读取失败，请检查后端连接。<button onClick={() => { void query.refetch() }}>重新加载</button></div>}
      {data?.missing_files.length ? <div role="alert" className="dashboard-alert">任务中有 {data.missing_files.length} 个文件缺失，当前统计不完整，请恢复文件。</div> : null}
      {!data ? <div role="status" className="dashboard-empty">{query.isError ? '暂时无法显示统计' : '正在读取任务统计…'}</div> : <>
        <div className="dashboard-statistics">
          <Statistic onInfo={() => show('info')} title="采集进度" description="已完成搜索组合" value={`${data.task.completed_groups} / ${data.task.total_groups}`} footer="查看采集任务" onClick={() => show('task')} badge={data.task.status === 'running' ? '采集中' : data.task.status === 'stopping' ? '停止中' : '未运行'}>
            <Progress value={progress} /><p>{current ? `当前搜索：${current.keyword}` : '采集当前未运行'}</p><p>{current ? `当前组合：初筛合格 ${current.qualified} / ${current.target ?? '—'} 帖` : `累计保存 ${data.metrics.collected_posts} 帖`}</p>
          </Statistic>
          <Statistic onInfo={() => show('info')} title="初筛合格帖子" description="通过自动初筛" value={data.metrics.qualified_posts} footer="进入人工审核" onClick={() => onReview(data.task.file)}>
            <DashboardChart mini points={data.trend} metric="qualified" /><p>待人工审核 {data.metrics.pending_review} 帖</p>
          </Statistic>
          <Statistic onInfo={() => show('info')} title="已采集图片" description="下载成功" value={imageCounts!.downloaded} footer="查看图片列表" onClick={() => show('images')}>
            <DashboardChart mini points={data.trend} metric="images" /><p>待下载 {imageCounts!.download_pending} 张 · 下载失败 {imageCounts!.download_failed} 张</p>
          </Statistic>
          <Statistic onInfo={() => show('info')} title="模型识别通过图片" description="符合图片识别规则" value={imageCounts!.qualified} footer="查看识别结果" onClick={() => show('recognition')}>
            <div className="dashboard-pass-progress"><Progress value={imageCounts!.pass_rate ?? 0} green /><span>{imageCounts!.pass_rate == null ? '—' : `${imageCounts!.pass_rate}%`}</span></div><p>已识别 {imageCounts!.recognized} · 待识别 {imageCounts!.pending}</p><p>未通过 {imageCounts!.unqualified} · 识别失败 {imageCounts!.failed}</p>
          </Statistic>
        </div>
        <section className="dashboard-sales dashboard-card"><header className="dashboard-sales-header"><div className="dashboard-tabs" role="tablist" aria-label="趋势指标"><button role="tab" aria-selected={metric === 'collected'} onClick={() => setMetric('collected')}>采集量</button><button role="tab" aria-selected={metric === 'qualified'} onClick={() => setMetric('qualified')}>初筛合格</button></div>
          <div className="dashboard-time-filters">{(['today', 'week', 'month', 'year'] as const).map((key, index) => <button key={key} aria-pressed={period === key} onClick={() => setTime(key)}>{['今日', '本周', '本月', '本年'][index]}</button>)}
            <div className="dashboard-date-wrap"><button className="dashboard-date-button" onClick={() => setDateOpen(!dateOpen)} aria-expanded={dateOpen} aria-label="选择日期范围"><span>{dashboardTime(data.range.start, true)}</span><span>→</span><span>{dashboardTime(data.range.end, true)}</span><img src={calendarIcon} alt="" /></button>
              {dateOpen && <div className="dashboard-date-panel"><label>开始<input type="datetime-local" value={custom.start} onChange={(event) => setCustom({ ...custom, start: event.target.value })} /></label><label>结束<input type="datetime-local" value={custom.end} onChange={(event) => setCustom({ ...custom, end: event.target.value })} /></label>
                {dateError && <p role="alert">结束时间须晚于开始时间</p>}<div><button onClick={() => setTime('task')}>整个任务</button><button onClick={() => { if (!custom.start || !custom.end || custom.start >= custom.end) { setDateError(true); return } setDateError(false); setRange({ start: new Date(custom.start).toISOString(), end: new Date(custom.end).toISOString() }); setPeriod('custom'); setDateOpen(false) }}>应用</button></div></div>}
            </div></div></header>
          <div className="dashboard-sales-body"><DashboardChart points={data.trend} metric={metric} /><div className="dashboard-ranking"><h3>搜索组合{metric === 'qualified' ? '初筛' : '采集'}排名</h3>{ranked.map((group, index) => <button key={group.keyword} onClick={() => { setKeyword(group.keyword); document.querySelector('.dashboard-offline')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}><span className={index < 3 ? 'rank rank-top' : 'rank'}>{index + 1}</span><span title={group.keyword}>{group.keyword}</span><span>{group[metric]}</span></button>)}</div></div>
        </section>
        <div className="dashboard-analysis"><section className="dashboard-card dashboard-performance"><header><h2>搜索组合表现</h2></header><div className="dashboard-performance-body"><div className="dashboard-performance-numbers"><div><p>已完成搜索组合</p><strong>{data.task.completed_groups} / {data.task.total_groups}</strong><Progress value={progress} /></div><div><p>当前组合目标进度</p><strong>{current?.target ? `${Math.round(percentage(current.qualified, current.target))}%` : '—'}</strong><Progress value={current ? percentage(current.qualified, current.target) : 0} /></div></div><GroupTable groups={data.groups} /><p className="dashboard-muted">每组初筛目标 {data.groups[0]?.target ?? '—'} 帖 · 共 {data.task.total_groups} 个搜索组合</p></div></section>
          <section className="dashboard-card dashboard-distribution"><header><h2>图片识别状态分布</h2><span>当前任务</span></header><div className="dashboard-distribution-body"><p>已判定 {imageCounts!.recognized} 张 · 模型通过率 {imageCounts!.pass_rate == null ? '—' : `${imageCounts!.pass_rate}%`}</p>
            <DashboardDonut total={imageCounts!.downloaded} segments={series.map((item) => ({ key: item.key, label: stateLabels[item.key], color: item.color, value: imageCounts![item.key] }))} onOpen={() => show('recognition')} onFilter={(state) => { show('recognition'); setImageFilter(state) }} />
            <div className="dashboard-legend">{series.map((item) => <button key={item.key} onClick={() => { show('recognition'); setImageFilter(item.key) }}><img src={item.icon} alt="" />{stateLabels[item.key]} {imageCounts![item.key]} 张</button>)}</div></div></section></div>
        <section className="dashboard-card dashboard-offline"><div className="dashboard-group-tabs" role="tablist" aria-label="搜索组合">{data.groups.map((group) => <button key={group.keyword} role="tab" aria-selected={keyword === group.keyword} onClick={() => setKeyword(group.keyword)}><h3 title={group.keyword}>{group.keyword}</h3><div><span>目标进度</span><svg viewBox="0 0 60 60"><circle cx="30" cy="30" r="25" stroke="#f0f0f0" strokeWidth="5" fill="none" /><circle cx="30" cy="30" r="25" stroke="#1890ff" strokeWidth="5" fill="none" pathLength="100" strokeDasharray={`${percentage(group.qualified, group.target)} 100`} transform="rotate(-90 30 30)" /><text x="30" y="34" textAnchor="middle" fontSize="11" fill="#8c8c8c">{group.target ? `${Math.round(percentage(group.qualified, group.target))}%` : '—'}</text></svg></div><p>{groupLabels[group.status]}</p></button>)}</div>
          <div className="dashboard-offline-chart"><div className="dashboard-chart-legend"><span>— 当前组合采集帖子</span><span>— 初筛合格帖子</span></div><DashboardChart points={selected ? data.group_trends[selected.keyword] || [] : []} cumulative /></div></section>
        <p className="dashboard-source-note">采集工作台 · 当前任务真实记录{data.unknown_time_posts > 0 ? ` · ${data.unknown_time_posts} 条历史帖子缺少保存时间，未计入时间趋势` : ''}</p>
      </>}
    </div></div>
    <Dialog.Root open={!!modal} onOpenChange={(open) => { if (!open) setModal(null) }}><Dialog.Portal><Dialog.Overlay className="dashboard-modal-overlay" /><Dialog.Content className="dashboard-modal" aria-describedby="dashboard-modal-body"><header><Dialog.Title>{modal === 'info' ? '统计口径说明' : modal === 'task' ? '当前采集任务' : modal === 'images' ? '已采集图片' : '模型识别结果'}</Dialog.Title><Dialog.Close aria-label="关闭弹窗"><img src={closeIcon} alt="" /></Dialog.Close></header>
      <div id="dashboard-modal-body" className="dashboard-modal-body">{data && (modal === 'info' ? <StatisticsHelp data={data} /> : modal === 'task' ? <><h3>{platform} · 场景图文采集</h3><p>当前文件：{data.task.file || '暂无文件'}</p><p>已完成 {data.task.completed_groups} / {data.task.total_groups} 组{current ? ` · 当前搜索：${current.keyword}` : ''}</p><GroupTable groups={data.groups} detailed /><p>当前任务：累计保存 {data.metrics.collected_posts} 帖，初筛合格 {data.metrics.qualified_posts} 帖。</p></> : <>
        <h3>{modal === 'images' ? `当前任务下载成功 ${imageCounts!.downloaded} 张` : `已完成识别 ${imageCounts!.recognized} 张 · 通过 ${imageCounts!.qualified} 张 · 通过率 ${imageCounts!.pass_rate == null ? '—' : `${imageCounts!.pass_rate}%`}`}</h3>
        {modal === 'images' ? <p>待下载 {imageCounts!.download_pending} 张 · 下载失败 {imageCounts!.download_failed} 张</p> : <div className="dashboard-image-filters"><button aria-pressed={imageFilter === 'all'} onClick={() => { setImageFilter('all'); setImagePage(0) }}>全部 {imageCounts!.downloaded}</button>{series.map((item) => <button key={item.key} aria-pressed={imageFilter === item.key} onClick={() => { setImageFilter(item.key); setImagePage(0) }}>{stateLabels[item.key]} {imageCounts![item.key]}</button>)}</div>}
        <div className="dashboard-table-scroll"><table><thead><tr><th>图片文件</th>{modal === 'images' && <th>所属搜索组合</th>}<th>{modal === 'images' ? '下载状态' : '识别状态'}</th><th>{modal === 'images' ? '模型识别状态' : '判定信息'}</th></tr></thead><tbody>{filteredImages.slice(shownPage * 5, shownPage * 5 + 5).map((image) => <tr key={image.url}><td>{image.url ? <a href={image.url} target="_blank" rel="noopener noreferrer">{image.note_id} / {image.name}</a> : image.name}</td>{modal === 'images' && <td>{image.keyword}</td>}<td>{modal === 'images' ? '下载成功' : stateLabels[image.status]}</td><td>{modal === 'images' ? stateLabels[image.status] : image.reason || (image.status === 'pending' ? '尚无明确判定，等待识别或复核' : '无已保存理由')}</td></tr>)}</tbody></table>{!filteredImages.length && <p className="dashboard-empty">暂无此类图片</p>}</div>
        <div className="dashboard-pagination"><span>展示 {filteredImages.length ? shownPage * 5 + 1 : 0}–{Math.min((shownPage + 1) * 5, filteredImages.length)} / {filteredImages.length} 张</span><button disabled={!shownPage} onClick={() => setImagePage(shownPage - 1)}>上一页</button><button disabled={shownPage >= pages - 1} onClick={() => setImagePage(shownPage + 1)}>下一页</button></div>
        {modal === 'recognition' && <p>待识别与识别失败均不等于未通过；通过率仅统计模型已有明确判定的图片。</p>}
      </>)}</div><footer>{modal === 'images' && <button className="dashboard-blue" onClick={() => show('recognition')}>查看识别结果</button>}<Dialog.Close className={modal === 'info' ? 'dashboard-primary' : ''}>{modal === 'info' ? '知道了' : '关闭'}</Dialog.Close></footer>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>
}

function StatisticsHelp({ data }: { data: DashboardSnapshot }) {
  const images = data.metrics.images
  return <div className="dashboard-statistics-help"><p>统计范围：当前任务及其关联轮次。日期筛选仅影响趋势与关键词排名；卡片与明细显示整个任务。</p>
    <h3>采集进度</h3><p>完成 {data.task.completed_groups} / {data.task.total_groups} 个搜索组合。达到初筛目标或已结束搜索的组合计为完成；中断不计为完成。保存帖子按“帖子 ID + 搜索组合”去重，包含已保存的排除记录。</p>
    <h3>初筛合格帖子</h3><p>自动初筛有效通过 {data.metrics.qualified_posts} 帖，不等于最终人工审核合格。双关键词命中、评论失败及账号／文本硬门槛继续生效；待人工审核包括尚无人工确认的初筛候选。</p>
    <h3>已采集图片</h3><p>仅统计当前任务成功保存且可读取的图片，同一文件只计一次。未下载或文件损坏不计入下载成功；未知历史下载失败原因不推测为明确失败。</p>
    <h3>模型识别通过图片</h3><p>通过率 = 模型通过 /（模型通过 + 模型未通过），当前 {images.qualified} / {images.recognized} = {images.pass_rate == null ? '—' : `${images.pass_rate}%`}。待识别、待复核与识别失败不计入分母。此处统计模型结果，人工覆盖保留在审核页。</p>
    <h3>时间趋势</h3><p>按记录的保存时间汇总，不使用帖子发布时间。缺少时间的历史记录不会猜测分布。本页只读取已有记录，不启动采集或识别。</p>
  </div>
}
