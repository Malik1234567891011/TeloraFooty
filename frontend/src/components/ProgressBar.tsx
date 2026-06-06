interface Props {
  value: number
  label?: string
}

export default function ProgressBar({ value, label }: Props) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div className="progress">
      <div className="progress-track">
        <div className="progress-fill" data-testid="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      {label && <div className="progress-label">{label}</div>}
    </div>
  )
}
