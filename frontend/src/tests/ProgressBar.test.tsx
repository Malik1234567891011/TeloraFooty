import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import ProgressBar from '../components/ProgressBar'

test('renders fill width from value and shows label', () => {
  render(<ProgressBar value={42} label="Scanning 4/8 windows" />)
  expect(screen.getByText('Scanning 4/8 windows')).toBeInTheDocument()
  expect(screen.getByTestId('progress-fill').style.width).toBe('42%')
})

test('clamps value to 0-100', () => {
  const { rerender } = render(<ProgressBar value={150} />)
  expect(screen.getByTestId('progress-fill').style.width).toBe('100%')
  rerender(<ProgressBar value={-10} />)
  expect(screen.getByTestId('progress-fill').style.width).toBe('0%')
})
