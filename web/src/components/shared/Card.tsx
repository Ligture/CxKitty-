import { cn } from '@/lib/utils'

export function Card({ className, children, onClick }: {
  className?: string; children: React.ReactNode; onClick?: () => void
}) {
  return (
    <div onClick={onClick}
      className={cn('rounded-lg border border-border bg-card p-4', className)}>
      {children}
    </div>
  )
}
