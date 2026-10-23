export function reviewPostQueryOptions<T>(file: string, offset: number,
  fetchPost: (file: string, offset: number, signal?: AbortSignal) => Promise<T>) {
  return {
    queryKey: ['dataBrowse', file, offset, 'humanReview'] as const,
    queryFn: async ({ queryKey, signal }: { queryKey: readonly ['dataBrowse', string, number, 'humanReview']; signal: AbortSignal }) => {
      const [, selectedFile, selectedOffset] = queryKey
      // Manual refetch bypasses enabled=false. Guard inside the function too.
      if (!selectedFile || !Number.isInteger(selectedOffset) || selectedOffset < 0) return null
      return fetchPost(selectedFile, selectedOffset, signal)
    },
    enabled: !!file && Number.isInteger(offset) && offset >= 0,
    retry: 1,
    staleTime: 30_000,
  }
}

export function savedImagePreviewUrl(image: { url: string; local: boolean }) {
  if (!image.local || !image.url.startsWith('/api/data/media/')) return image.url
  return image.url + (image.url.includes('?') ? '&' : '?') + 'preview=true'
}
