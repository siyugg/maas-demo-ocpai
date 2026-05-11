import type { MapData } from '../types'

export async function fetchMapData(): Promise<MapData> {
  const resp = await fetch('/weather/map-data')
  if (!resp.ok) throw new Error(`Weather API error: ${resp.status}`)
  return resp.json()
}
