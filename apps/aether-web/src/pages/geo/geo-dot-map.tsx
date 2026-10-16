import { useMemo } from 'react';
import {
  COUNTRY_CENTROIDS, ISO2_COUNTRY, WORLD_DOT_COLS, WORLD_DOT_LAT_TOP, WORLD_DOT_ROWS, WORLD_DOT_STEP,
} from './geo-world-dots';

/** Equirectangular map space: x = lon + 180 (0–360), y = latTop − lat. */
const MAP_W = 360;
const MAP_H = WORLD_DOT_ROWS.length * WORLD_DOT_STEP;

function project(lon: number, lat: number): [number, number] {
  return [lon + 180, WORLD_DOT_LAT_TOP - lat];
}

/** One <path> of tiny circles for the land dots (≈2k dots, one DOM node). */
function landPath(): string {
  const r = 0.62;
  const parts: string[] = [];
  WORLD_DOT_ROWS.forEach((row, ri) => {
    for (let ci = 0; ci < WORLD_DOT_COLS; ci++) {
      const nibble = parseInt(row[ci >> 2] ?? '0', 16);
      if (!(nibble & (8 >> (ci & 3)))) continue;
      const x = ci * WORLD_DOT_STEP + WORLD_DOT_STEP / 2;
      const y = ri * WORLD_DOT_STEP + WORLD_DOT_STEP / 2;
      parts.push(`M${(x - r).toFixed(2)} ${y.toFixed(2)}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`);
    }
  });
  return parts.join('');
}

const LAND_PATH = landPath();

/** Resolve a [lon, lat] for a geography: explicit coordinates, ISO2 code or country name. */
export function geoPosition(geo: Record<string, unknown>): [number, number] | null {
  const c = (geo.centroid && typeof geo.centroid === 'object' ? geo.centroid : {}) as Record<string, unknown>;
  const latRaw = geo.latitude ?? geo.lat ?? c.latitude ?? c.lat;
  const lonRaw = geo.longitude ?? geo.lon ?? geo.lng ?? c.longitude ?? c.lon ?? c.lng;
  if (latRaw !== undefined && latRaw !== null && lonRaw !== undefined && lonRaw !== null) {
    const lat = Number(latRaw);
    const lon = Number(lonRaw);
    if (Number.isFinite(lat) && Number.isFinite(lon)) return [lon, lat];
  }
  const id = String(geo.geo_id ?? '').trim().toLowerCase();
  const name = String(geo.geo_name ?? '').trim().toLowerCase();
  const key = ISO2_COUNTRY[id] ?? (name === 'united states' || name === 'usa' ? 'united states of america' : name);
  const hit = COUNTRY_CENTROIDS[key];
  return hit ? [hit[0], hit[1]] : null;
}

export interface MapMarker {
  readonly id: string;
  readonly label: string;
  readonly position: [number, number];
  /** 0–1 relative weight for the active lens. */
  readonly weight: number;
  readonly valueLabel: string;
  readonly onSelect?: () => void;
}

/**
 * Stylized dot map (design: Aether Geography). Base land dots are static
 * geography; markers are the caller's real geo summary rows. `focus` zooms the
 * view onto one position (a drilled-into country).
 */
export function GeoDotMap({
  markers,
  focus,
  color,
  label,
}: {
  readonly markers: readonly MapMarker[];
  readonly focus: [number, number] | null;
  readonly color: string;
  readonly label: string;
}) {
  const viewBox = useMemo(() => {
    if (!focus) return `0 0 ${MAP_W} ${MAP_H}`;
    const [x, y] = project(focus[0], focus[1]);
    const w = 96;
    const h = 48;
    const x0 = Math.max(0, Math.min(MAP_W - w, x - w / 2));
    const y0 = Math.max(0, Math.min(MAP_H - h, y - h / 2));
    return `${x0.toFixed(1)} ${y0.toFixed(1)} ${w} ${h}`;
  }, [focus]);
  const scale = focus ? 0.4 : 1;

  return (
    <svg
      viewBox={viewBox}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={label}
      className="block h-auto w-full"
      style={{ transition: 'all .4s cubic-bezier(.22,1,.36,1)' }}
      data-testid="geo-dot-map"
    >
      <path d={LAND_PATH} fill="var(--ae-line)" opacity={0.75} />
      {focus && (() => {
        const [x, y] = project(focus[0], focus[1]);
        return <circle cx={x} cy={y} r={2.2} fill="none" stroke="var(--ae-ink)" strokeWidth={0.25} strokeDasharray="0.8 0.6" />;
      })()}
      {markers.map(m => {
        const [x, y] = project(m.position[0], m.position[1]);
        const r = (1.6 + Math.sqrt(Math.max(0, m.weight)) * 6) * scale;
        return (
          <g
            key={m.id}
            role={m.onSelect ? 'button' : undefined}
            tabIndex={m.onSelect ? 0 : undefined}
            aria-label={`${m.label}: ${m.valueLabel}`}
            onClick={m.onSelect}
            onKeyDown={m.onSelect ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); m.onSelect?.(); } } : undefined}
            style={{ cursor: m.onSelect ? 'pointer' : 'default', outline: 'none' }}
            className="ae-focus"
          >
            <title>{`${m.label} · ${m.valueLabel}`}</title>
            <circle cx={x} cy={y} r={r * 1.9} fill={color} opacity={0.14} />
            <circle cx={x} cy={y} r={r} fill={color} opacity={0.78} stroke="var(--ae-raised)" strokeWidth={0.35 * scale} />
          </g>
        );
      })}
    </svg>
  );
}
