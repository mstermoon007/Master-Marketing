export function today(): string {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

export function daysAgo(days: number): string {
  const now = new Date()
  now.setDate(now.getDate() - days)
  const offset = now.getTimezoneOffset() * 60000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

export function formatDateTime(value?: string | null): string {
  if (!value) return ''
  return String(value).replace('T', ' ').replace('.000Z', '').replace('Z', '')
}
