import yes from '@/assets/review/imgSvg13.svg'
import yesSelected from '@/assets/review/imgSvg6.svg'
import no from '@/assets/review/imgSvg7.svg'
import noSelected from '@/assets/review/imgSvg14.svg'
import reset from '@/assets/review/imgSvg11.svg'
import account from '@/assets/review/imgSvg10.svg'
import external from '@/assets/review/imgSvg12.svg'
import previous from '@/assets/review/imgSvg8.svg'
import next from '@/assets/review/imgSvg9.svg'
import refresh from '@/assets/review/imgSvg5.svg'

const icons = { yes, yesSelected, no, noSelected, reset, account, external, previous, next, refresh }
export function ReviewIcon({ name }: { name: keyof typeof icons }) {
  return <img src={icons[name]} alt="" aria-hidden="true" className="review-icon" />
}
