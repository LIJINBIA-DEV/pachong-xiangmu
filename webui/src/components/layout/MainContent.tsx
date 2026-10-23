import { Terminal } from '@/components/console/Terminal'
import { useLogWebSocket } from '@/hooks/useWebSocket'

export function MainContent() {
  // Connect to WebSocket for logs
  useLogWebSocket()

  return (
    <div className="min-h-0 flex-1 flex flex-col relative z-10">
      <Terminal fullHeight />
    </div>
  )
}
