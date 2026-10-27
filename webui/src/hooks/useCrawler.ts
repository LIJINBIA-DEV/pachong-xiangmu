import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { crawlerApi, configApi } from '@/lib/api'
import { useCrawlerStore } from '@/store/crawlerStore'
import type { CrawlerConfig } from '@/types/crawler'
import axios from 'axios'

export function useCrawlerStatus() {
  const queryClient = useQueryClient()
  const setRunningInfo = useCrawlerStore((state) => state.setRunningInfo)

  return useQuery({
    queryKey: ['crawlerStatus'],
    queryFn: async () => {
      const { data } = await crawlerApi.getStatus()
      const previous = useCrawlerStore.getState().status
      useCrawlerStore.setState({ status: data.status, stage: data.stage ?? (data.status === 'running' ? 'running' : 'idle') })
      setRunningInfo(data.platform, data.crawler_type, data.started_at)
      if ((previous === 'running' || previous === 'stopping') && data.status !== 'running' && data.status !== 'stopping') {
        void queryClient.invalidateQueries({ queryKey: ['dataFiles'] })
        void queryClient.invalidateQueries({ queryKey: ['collectionTasks'] })
        void queryClient.invalidateQueries({ queryKey: ['dataBrowse'] })
          void queryClient.invalidateQueries({ queryKey: ['manualReview'] })
          void queryClient.invalidateQueries({ queryKey: ['imageSubject'] })
        void queryClient.invalidateQueries({ queryKey: ['supplement'] })
        void queryClient.invalidateQueries({ queryKey: ['crawlerLogs'] })
      }
      return data
    },
    refetchInterval: 2000,
  })
}

export function useStartCrawler() {
  const queryClient = useQueryClient()
  const setStatus = useCrawlerStore((state) => state.setStatus)
  const clearLogs = useCrawlerStore((state) => state.clearLogs)

  return useMutation({
    mutationFn: (config: CrawlerConfig) => crawlerApi.start(config),
    onMutate: () => {
      clearLogs()
      setStatus('running')
    },
    onSuccess: () => {
      toast.success('正在准备采集，登录验证通过后开始运行')
      queryClient.invalidateQueries({ queryKey: ['crawlerStatus'] })
    },
    onError: (error: Error) => {
      setStatus('idle')
      const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null
      toast.error(`Failed to start crawler: ${typeof detail === 'string' ? detail : error.message}`)
    },
  })
}

export function useStopCrawler() {
  const queryClient = useQueryClient()
  const setStatus = useCrawlerStore((state) => state.setStatus)

  return useMutation({
    mutationFn: () => crawlerApi.stop(),
    onMutate: () => {
      setStatus('stopping')
    },
    onSuccess: () => {
      toast.success('Crawler stopped')
      setStatus('idle')
      queryClient.invalidateQueries({ queryKey: ['crawlerStatus'] })
      queryClient.invalidateQueries({ queryKey: ['dataFiles'] })
      queryClient.invalidateQueries({ queryKey: ['collectionTasks'] })
      queryClient.invalidateQueries({ queryKey: ['dataBrowse'] })
      queryClient.invalidateQueries({ queryKey: ['crawlerLogs'] })
    },
    onError: (error: Error) => {
      toast.error(`Failed to stop crawler: ${error.message}`)
    },
  })
}

export function useCrawlerLogs() {
  const setLogs = useCrawlerStore((state) => state.setLogs)

  return useQuery({
    queryKey: ['crawlerLogs'],
    queryFn: async () => {
      const { data } = await crawlerApi.getLogs(500)
      setLogs(data.logs)
      return data.logs
    },
    refetchInterval: false, // Use WebSocket instead
  })
}

export function usePlatforms() {
  return useQuery({
    queryKey: ['platforms'],
    queryFn: async () => {
      const { data } = await configApi.getPlatforms()
      return data.platforms
    },
    staleTime: Infinity,
  })
}

export function useConfigOptions() {
  return useQuery({
    queryKey: ['configOptions'],
    queryFn: async () => {
      const { data } = await configApi.getOptions()
      return data
    },
    staleTime: Infinity,
  })
}
