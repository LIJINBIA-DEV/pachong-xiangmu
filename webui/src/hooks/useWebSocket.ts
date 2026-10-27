import { useEffect } from 'react'
import { useCrawlerStore } from '@/store/crawlerStore'
import type { LogEntry } from '@/types/crawler'
import { createLogBuffer } from '@/lib/logBuffer'

const logBuffer = createLogBuffer((logs, session) => useCrawlerStore.getState().receiveLogs(logs, session))

// 模块级单例，确保全局只有一个 WebSocket 连接
let globalWs: WebSocket | null = null
let globalReconnectTimer: ReturnType<typeof setTimeout> | null = null
let connectionCount = 0  // 跟踪连接使用者数量

export function useLogWebSocket() {
  useEffect(() => {
    connectionCount++

    const connect = () => {
      if (globalReconnectTimer) {
        clearTimeout(globalReconnectTimer)
        globalReconnectTimer = null
      }

      // 如果已经连接或正在连接，不重复创建
      if (globalWs && (globalWs.readyState === WebSocket.OPEN || globalWs.readyState === WebSocket.CONNECTING)) {
        return
      }

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const wsUrl = `${protocol}//${host}/api/ws/logs`

      const ws = new WebSocket(wsUrl)
      globalWs = ws

      ws.onopen = () => {
        if (globalWs !== ws) return
        console.log('WebSocket connected')
      }

      ws.onmessage = (event) => {
        if (globalWs !== ws) return
        if (event.data === 'ping') {
          ws.send('pong')
          return
        }
        if (event.data === 'pong') {
          return
        }

        try {
          const message = JSON.parse(event.data)
          if (message.type === 'log_snapshot' && Array.isArray(message.logs)) {
            logBuffer.push(message.logs, message.session_id)
          } else if (message.id && message.message) {
            logBuffer.push([message as LogEntry], message.session_id)
          }
        } catch (e) {
          console.warn('Failed to parse WebSocket message:', event.data)
        }
      }

      ws.onclose = () => {
        if (globalWs !== ws) return
        logBuffer.flush()
        console.log('WebSocket disconnected')
        globalWs = null
        // 只在还有使用者时才重连
        if (connectionCount > 0) {
          globalReconnectTimer = setTimeout(connect, 2000)
        }
      }

      ws.onerror = (error) => {
        if (globalWs !== ws) return
        console.error('WebSocket error:', error)
      }
    }

    // 首次连接
    connect()

    // Heartbeat
    const heartbeat = setInterval(() => {
      if (globalWs && globalWs.readyState === WebSocket.OPEN) {
        globalWs.send('ping')
      }
    }, 30000)

    return () => {
      connectionCount--
      clearInterval(heartbeat)

      // 只在没有使用者时才断开连接
      if (connectionCount === 0) {
        logBuffer.flush()
        if (globalReconnectTimer) {
          clearTimeout(globalReconnectTimer)
          globalReconnectTimer = null
        }
        if (globalWs) {
          const ws = globalWs
          globalWs = null
          ws.close()
        }
      }
    }
  }, [])  // 空依赖数组

  return { ws: globalWs }
}
