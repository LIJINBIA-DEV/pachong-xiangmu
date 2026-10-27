import { DataBrowser } from './DataBrowser'

export function DataManagementPage({ onReview }: { onReview?: (file: string, postKey: string) => void }) {
  return <DataBrowser onReview={onReview} />
}
