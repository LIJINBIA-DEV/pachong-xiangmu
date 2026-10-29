import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildSync } from 'esbuild'
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const cache = resolve('node_modules/.cache')
mkdirSync(cache, { recursive: true })
const directory = mkdtempSync(join(cache, 'collection-options-'))
const output = join(directory, 'render.mjs')
const code = buildSync({
  stdin: { contents: `
    import React from 'react'
    import { renderToStaticMarkup } from 'react-dom/server'
    import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
    import { I18nextProvider } from 'react-i18next'
    import { createInstance } from 'i18next'
    import configTranslations from './src/i18n/locales/zh-CN/config.json'
    import workspace from './src/i18n/locales/zh-CN/workspace.json'
    import dataTranslations from './src/i18n/locales/zh-CN/data.json'
    import { CrawlerConfigPanel } from './src/components/config/CrawlerConfigPanel'
    import { CollectionProgressBar } from './src/components/config/CollectionProgressBar'
    import { ManualReviewPage } from './src/components/data/ManualReviewPage'
    import { withReviewOutcomes } from './src/lib/reviewOutcome'
    import { WeiboQRCodeLogin } from './src/components/config/WeiboQRCodeLogin'
    import api, { crawlerApi } from './src/lib/api'
    import { useCrawlerStore } from './src/store/crawlerStore'
    const initial = useCrawlerStore.getInitialState()
    const defaults = { ...initial.config }
    export async function loginRequest(mode) {
      const original = api.defaults.adapter
      let body
      api.defaults.adapter = async config => {
        body = JSON.parse(config.data)
        return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
      }
      try { await crawlerApi.startQRLogin('xhs', false, mode); return body }
      finally { api.defaults.adapter = original }
    }
    export async function renderQR(state) {
      const client = new QueryClient()
      client.setQueryData(['qrLogin', 'xhs'], state)
      const i18n = createInstance()
      await i18n.init({ lng: 'zh-CN', resources: { 'zh-CN': { config: configTranslations } }, interpolation: { escapeValue: false } })
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(I18nextProvider, { i18n }, React.createElement(WeiboQRCodeLogin, { platform: 'xhs', loginEnvironment: 'local', disabled: false, onReady() {}, compact: true }))))
      client.clear()
      return html
    }
    export function renderProgress(runtime, progress) {
      Object.assign(initial, { status: 'idle', stage: 'idle', startedAt: null }, runtime)
      useCrawlerStore.setState(initial, true)
      const client = new QueryClient()
      client.setQueryData(['collectionProgress', initial.status, initial.startedAt], progress)
      const props = { active: true, busy: initial.status === 'running', starting: false, stopping: false, startDisabled: false, onStart() {}, onStop() {} }
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(CollectionProgressBar, props)))
      client.clear()
      Object.assign(initial, { status: 'idle', stage: 'idle', startedAt: null })
      return html
    }
    export async function renderReview(entries) {
      const file = 'xhs/posts.xlsx'
      const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
      client.setQueryData(['collectionTasks'], [{ id: 'task', title: '测试任务', platform: 'xhs', primary_file: file, modified_at: 1793111874,
        files: [{ path: file, name: 'posts.xlsx', type: 'xlsx', file_kind: 'collection' }] }])
      client.setQueryData(['manualReview', file], withReviewOutcomes({ entries, total: Object.keys(entries).length, completed: 0 }))
      client.setQueryData(['reviewExportList'], [])
      client.setQueryData(['supplement', file], { supported: false })
      const i18n = createInstance()
      await i18n.init({ lng: 'zh-CN', resources: { 'zh-CN': { workspace, data: dataTranslations } }, interpolation: { escapeValue: false } })
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(I18nextProvider, { i18n }, React.createElement(ManualReviewPage))))
      client.clear()
      return html
    }
    export async function render(config, keySaved = false) {
      // Zustand uses its initial snapshot during server rendering.
      initial.config = { ...defaults, platform: 'xhs', login_environment: 'local', ...config }
      useCrawlerStore.setState(initial, true)
      const before = JSON.stringify(useCrawlerStore.getState().config)
      const i18n = createInstance()
      await i18n.init({ lng: 'zh-CN', resources: { 'zh-CN': { config: configTranslations, workspace, data: dataTranslations } }, interpolation: { escapeValue: false } })
      const client = new QueryClient()
      client.setQueryData(['semanticKeySettings'], { key_configured: keySaved })
      const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(I18nextProvider, { i18n }, React.createElement(CrawlerConfigPanel))))
      client.clear()
      return { html, unchanged: before === JSON.stringify(useCrawlerStore.getState().config) }
    }
  `, resolveDir: process.cwd(), loader: 'tsx' },
  bundle: true, write: false, format: 'esm', platform: 'node', packages: 'external',
  tsconfig: 'tsconfig.json', loader: { '.svg': 'dataurl', '.css': 'empty' },
}).outputFiles[0].text
writeFileSync(output, code)
const { render, renderProgress, renderQR, loginRequest, renderReview } = await import(pathToFileURL(output))
process.on('exit', () => rmSync(directory, { recursive: true, force: true }))

const content = html => html.slice(html.indexOf('<section class="config-card config-images"'))

test('automatic passes do not create manual work and the empty queue is explicit', async () => {
  const entries = Object.fromEntries(Array.from({ length: 6 }, (_, i) => [String(i), {
    screening_passed: true, account: null, images: {}, review_images: [], decision: null,
  }]))
  const html = await renderReview(entries)
  assert.ok(html.includes('待人工处理 0 帖'))
  assert.ok(html.includes('本任务共 6 帖'))
  assert.ok(html.includes('本任务暂无需要人工复核的帖子'))
  assert.ok(html.includes('查看全部帖子'))
  assert.ok(html.includes('value="unmarked" selected=""'))
  assert.ok(!html.includes('review-work-area'))
})

test('QR request respects selected environment rather than forcing server login', async () => {
  for (const mode of ['local', 'server', 'auto']) {
    assert.deepEqual(await loginRequest(mode), { refresh: false, login_environment: mode })
  }
})

test('local verification tells user to use retained window and hides QR after login', async () => {
  const state = { local_browser: true, busy: true, saved_session: false, qr_image: 'data:image/png;base64,test' }
  const verification = await renderQR({ ...state, status: 'verification_required', reason: 'login_network_restricted' })
  assert.ok(verification.includes('当前窗口会保留'))
  assert.ok(!verification.includes('alt="小红书登录二维码"'))
  const waiting = await renderQR({ ...state, status: 'waiting', expires_at: Date.now() / 1000 + 600 })
  assert.ok(waiting.includes('alt="小红书登录二维码"'))
  assert.ok(waiting.includes('二维码有效期以官方页面为准'))
  const ready = await renderQR({ ...state, status: 'authenticated', busy: false, saved_session: true })
  assert.ok(ready.includes('登录成功，状态已保存'))
  assert.ok(!ready.includes('config-qr-placeholder'))
})

test('configuration exposes comments and media without image recognition', async () => {
  for (const platform of ['xhs', 'wb']) {
    const { html, unchanged } = await render({ platform, enable_comments: true, image_subject_recognition: true })
    const block = content(html)
    for (const title of ['评论采集', '媒体下载']) assert.ok(block.includes(`>${title}</h3>`))
    assert.ok(!block.includes('图片识别'))
    assert.ok(!block.includes('自动识别'))
    assert.ok(!block.includes('config-image-fields'))
    assert.ok(unchanged)
  }
})

test('comment replies are explained rather than checked and disabled when comments are off', async () => {
  const { html } = await render({ enable_comments: false, enable_sub_comments: true })
  const block = content(html)
  assert.ok(block.includes('先开启“采集帖子评论”'))
  assert.ok(!block.includes('aria-label="同时采集评论下的回复"'))
})

test('semantic collection hides automatic sampling details and reply extraction controls', async () => {
  const { html } = await render({ platform: 'wb', semantic_filter: true, enable_comments: true, login_environment: 'server', login_type: 'cookie' })
  assert.ok(!content(html).includes('先用标题和正文判断'))
  assert.ok(!content(html).includes('aria-label="采集帖子评论"'))
  assert.ok(!content(html).includes('每帖最多补采 5 条'))
  assert.ok(!content(html).includes('目标帖数 × 5'))
  assert.ok(!content(html).includes('aria-label="同时采集评论下的回复"'))
  assert.ok(html.includes('采集浏览器：后台运行'))
  assert.ok(!content(html).includes('采集浏览器：后台运行'))
})

test('invalid dates stay visible and the start button remains clickable for guided validation', async () => {
  const { html } = await render({ publish_time_range: 'custom', publish_start_date: '2026-10-10', publish_end_date: '2026-10-01' })
  assert.ok(html.indexOf('config-publication-range') < html.indexOf('keyword-search-input'))
  assert.ok(html.includes('aria-label="开始日期"'))
  assert.ok(html.includes('aria-label="结束日期"'))
  assert.ok(html.includes('开始日期不能晚于结束日期'))
  const start = html.match(/<button\b[^>]*class="[^"]*\bconfig-primary\b[^"]*"[^>]*>/)?.[0]
  assert.ok(start)
  assert.ok(!/\sdisabled(?:=|\s|>)/.test(start))
})


test('collection has one topic entry with an optional opinion filter, without a rule selector', async () => {
  const plain = (await render({ semantic_filter: true, semantic_rule: 'topic' })).html
  assert.ok(plain.includes('只关注某种评价'))
  assert.ok(plain.includes('请输入采集主题'))
  assert.ok(!plain.includes('aria-label="筛选规则"'))
  assert.ok(!plain.includes('填写你关注的评价或看法'))
  const focused = (await render({ semantic_filter: true, semantic_rule: 'scene' })).html
  assert.ok(focused.includes('请输入采集主题'))
  assert.ok(focused.includes('填写你关注的评价或看法'))
  assert.ok(!focused.includes('请输入评价对象'))
  assert.ok(!focused.includes('评价什么？'))
  const off = (await render({ semantic_filter: false, semantic_rule: 'scene' })).html
  assert.ok(!off.includes('填写你关注的评价或看法'))
  const commentsOff = (await render({ enable_comments: false })).html
  assert.ok(commentsOff.includes('再启用语义筛选和可选评价条件'))
})


test('normal configuration omits start page and experimental wording', async () => {
  const { html, unchanged } = await render({ start_page: 6, semantic_filter: true })
  assert.ok(!html.includes('起始页'))
  assert.ok(!html.includes('试运行'))
  assert.ok(html.includes('语义筛选'))
  assert.ok(unchanged)
})


test('progress waits for login and never presents the previous task as the new run', () => {
  const old = { status: 'idle', started_at: 'old', task_id: 'old-task', percent: 100, qualified: 5, target: 5 }
  const html = renderProgress({ status: 'running', stage: 'waiting_login', startedAt: null }, old)
  assert.ok(html.includes('等待登录，尚未开始采集'))
  assert.ok(!html.includes('100%'))
  assert.ok(!html.includes('aria-valuenow'))
  assert.ok(html.includes('停止采集'))
})

test('live progress displays actual post and comment units and keeps the result after finishing', () => {
  const actual = { status: 'running', started_at: 'now', task_id: 'new-task', percent: 40, checked: 8, saved: 2, qualified: 2, target: 5, comments: 15, images: 3, completed_topics: 0, total_topics: 1, current_keyword: '采集主题' }
  const html = renderProgress({ status: 'running', stage: 'running', startedAt: 'now' }, actual)
  assert.ok(html.includes('aria-valuenow="40"'))
  assert.ok(html.includes('自动筛选通过 2 / 目标 5 帖'))
  for (const label of ['已处理候选帖', '已记录帖子', '自动筛选通过']) {
    assert.ok(html.includes(`aria-label="${label}说明"`))
  }
  assert.ok(!html.includes('已记录不代表筛选通过'))
  assert.ok(!html.includes('role="tooltip"'))
  assert.ok(html.includes('已采评论'))
  assert.ok(html.includes('已下载图片'))
  assert.ok(!html.includes('开始爬虫'))
  const final = renderProgress({}, { ...actual, status: 'idle', run_status: 'stopped' })
  assert.ok(final.includes('采集已停止'))
  assert.ok(final.includes('开始爬虫'))
})


test('saved Jev key remains visibly configured after page reload without returning a secret', async () => {
  const { html } = await render({ semantic_filter: true }, true)
  assert.ok(html.includes('已保存，留空继续使用；输入新 Key 可更换'))
  assert.ok(html.includes('已配置，刷新和重启后继续使用。'))
  assert.ok(html.includes('保存 Key'))
  assert.ok(html.includes('清除已保存 Key'))
  assert.ok(!html.includes('仅在当前页面临时保留'))
})
