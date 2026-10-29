import { DataBrowser } from './DataBrowser'

export function DataManagementPage({ initialFile, onReview }: { initialFile?: string; onReview?: (file: string, postKey: string) => void }) {
  return <DataBrowser initialFile={initialFile} onReview={onReview} />
}
