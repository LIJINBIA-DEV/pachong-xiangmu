import type { MutationObserverOptions, QueryClient } from '@tanstack/react-query'
import type { ManualReviewResponse } from '@/types/dataBrowser'
import { applyReviewChange, mergeReviewResponse } from './reviewOutcome'
import type { ReviewChange } from './reviewOutcome'

export type SavedReviewChange = ReviewChange & { file: string }

export function reviewSaveOptions(queryClient: QueryClient, persist: (change: SavedReviewChange) => Promise<ManualReviewResponse>):
  MutationObserverOptions<ManualReviewResponse, Error, SavedReviewChange, { previous?: ManualReviewResponse }> {
  return {
    mutationFn: persist,
    onMutate: async (change) => {
      const queryKey = ['manualReview', change.file]
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<ManualReviewResponse>(queryKey)
      if (previous) queryClient.setQueryData(queryKey, applyReviewChange(previous, change))
      return { previous }
    },
    onError: (_error, change, context) => {
      if (context?.previous) queryClient.setQueryData(['manualReview', change.file], context.previous)
      void queryClient.invalidateQueries({ queryKey: ['manualReview', change.file] })
    },
    onSuccess: (data, change) => {
      const queryKey = ['manualReview', change.file]
      const merged = mergeReviewResponse(queryClient.getQueryData<ManualReviewResponse>(queryKey), data)
      if (merged) queryClient.setQueryData(queryKey, merged)
      else void queryClient.invalidateQueries({ queryKey })
      void queryClient.invalidateQueries({ queryKey: ['supplement', change.file] })
    },
  }
}
