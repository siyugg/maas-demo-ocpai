import { useEffect, useState, useRef } from 'react'
import { MapContainer, TileLayer, CircleMarker, Tooltip, useMap } from 'react-leaflet'
import type { MapArea, MapData } from '../types'
import { fetchMapData } from '../api/weather'

const FORECAST_COLORS: Record<string, string> = {
  'Fair': '#facc15',
  'Fair (Day)': '#facc15',
  'Fair (Night)': '#f59e0b',
  'Fair & Warm': '#f97316',
  'Partly Cloudy': '#93c5fd',
  'Partly Cloudy (Day)': '#93c5fd',
  'Partly Cloudy (Night)': '#6366f1',
  'Cloudy': '#9ca3af',
  'Hazy': '#d1d5db',
  'Slightly Hazy': '#e5e7eb',
  'Windy': '#67e8f9',
  'Mist': '#bfdbfe',
  'Light Rain': '#60a5fa',
  'Light Showers': '#60a5fa',
  'Showers': '#3b82f6',
  'Rain': '#2563eb',
  'Heavy Rain': '#1d4ed8',
  'Heavy Showers': '#1d4ed8',
  'Thundery Showers': '#7c3aed',
  'Heavy Thundery Showers': '#5b21b6',
  'Heavy Thundery Showers with Gusty Winds': '#4c1d95',
  'Snow': '#f0f9ff',
}

function getForecastColor(forecast: string): string {
  return FORECAST_COLORS[forecast] ?? '#94a3b8'
}

function getForecastIcon(forecast: string): string {
  if (forecast.includes('Thunder')) return '⛈'
  if (forecast.includes('Heavy')) return '🌧'
  if (forecast.includes('Shower') || forecast.includes('Rain')) return '🌦'
  if (forecast.includes('Cloudy')) return '⛅'
  if (forecast.includes('Fair') || forecast.includes('Sunny')) return '☀️'
  if (forecast.includes('Hazy') || forecast.includes('Mist')) return '🌫'
  if (forecast.includes('Windy')) return '💨'
  return '🌤'
}

// Component to fly to highlighted area
function MapFlyTo({ areas, areaData }: { areas: string[]; areaData: MapArea[] }) {
  const map = useMap()
  useEffect(() => {
    if (!areas.length) return
    const found = areaData.find(a => areas.some(h => a.name.toLowerCase().includes(h.toLowerCase())))
    if (found) {
      map.flyTo([found.lat, found.lng], 13, { animate: true, duration: 1.2 })
    }
  }, [areas, areaData, map])
  return null
}

interface Props {
  highlightedAreas: string[]
}

export default function SingaporeMap({ highlightedAreas }: Props) {
  const [mapData, setMapData] = useState<MapData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string>('')

  useEffect(() => {
    let retryTimeout: ReturnType<typeof setTimeout>

    const load = async (isRetry = false) => {
      try {
        const data = await fetchMapData()
        setMapData(data)
        setLastUpdated(new Date().toLocaleTimeString('en-SG'))
        setError(null)
      } catch (e) {
        setError('Weather data unavailable — retrying…')
        // Retry sooner on failure (5s), then fall back to 30s cadence
        if (!isRetry) {
          retryTimeout = setTimeout(() => load(true), 5000)
        }
      }
    }

    load()
    const interval = setInterval(() => load(), 30_000)
    return () => { clearInterval(interval); clearTimeout(retryTimeout) }
  }, [])

  const areas = mapData?.areas ?? []

  return (
    <div className="flex flex-col h-full">
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-rh-border bg-rh-dark shrink-0">
        <span className="text-sm font-medium text-rh-text">Singapore Weather Map</span>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-rh-muted">Updated {lastUpdated}</span>
          )}
          <span className="text-xs text-rh-muted">
            {mapData?.valid_period?.text ?? ''}
          </span>
        </div>
      </div>

      {/* Map */}
      <div className="flex-1 relative min-h-0">
        {error ? (
          <div className="flex items-center justify-center h-full text-rh-muted text-sm">
            {error}
          </div>
        ) : (
          <MapContainer
            center={[1.3521, 103.8198]}
            zoom={11}
            className="h-full w-full"
            zoomControl={true}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
            />

            {areas.map(area => {
              const isHighlighted = highlightedAreas.some(h =>
                area.name.toLowerCase().includes(h.toLowerCase())
              )
              const color = getForecastColor(area.forecast)

              return (
                <CircleMarker
                  key={area.name}
                  center={[area.lat, area.lng]}
                  radius={isHighlighted ? 14 : 9}
                  pathOptions={{
                    fillColor: color,
                    fillOpacity: isHighlighted ? 0.95 : 0.75,
                    color: isHighlighted ? '#EE0000' : color,
                    weight: isHighlighted ? 3 : 1,
                  }}
                >
                  <Tooltip direction="top" offset={[0, -8]} opacity={0.95}>
                    <div className="text-xs">
                      <div className="font-medium">{area.name}</div>
                      <div className="text-rh-muted">
                        {getForecastIcon(area.forecast)} {area.forecast}
                      </div>
                    </div>
                  </Tooltip>
                </CircleMarker>
              )
            })}

            <MapFlyTo areas={highlightedAreas} areaData={areas} />
          </MapContainer>
        )}
      </div>

      {/* Legend */}
      <div className="border-t border-rh-border bg-rh-dark px-4 py-2 shrink-0">
        <div className="flex flex-wrap gap-3 text-xs text-rh-muted">
          {[
            { label: 'Fair/Sunny', color: '#facc15' },
            { label: 'Partly Cloudy', color: '#93c5fd' },
            { label: 'Cloudy', color: '#9ca3af' },
            { label: 'Showers', color: '#3b82f6' },
            { label: 'Heavy Rain', color: '#1d4ed8' },
            { label: 'Thundery', color: '#7c3aed' },
          ].map(({ label, color }) => (
            <span key={label} className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: color }} />
              {label}
            </span>
          ))}
          {highlightedAreas.length > 0 && (
            <span className="flex items-center gap-1 text-rh-red">
              <span className="w-2.5 h-2.5 rounded-full inline-block border-2 border-rh-red bg-transparent" />
              Highlighted from chat
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
