/**
 * Coarse continent outlines ([lon, lat] rings) for the Graph globe's dot map,
 * taken from the Claude Design handoff (Aether Graph Trace). They are drawing
 * geometry only — no data is attached to them.
 */
const LAND: ReadonlyArray<ReadonlyArray<readonly [number, number]>> = [
  [[-168, 66], [-140, 70], [-95, 72], [-80, 73], [-62, 60], [-55, 50], [-67, 45], [-76, 35], [-81, 25], [-97, 26], [-105, 22], [-118, 32], [-124, 40], [-125, 50], [-140, 59], [-168, 66]],
  [[-105, 22], [-92, 14], [-83, 9], [-77, 8], [-80, 12], [-90, 18], [-97, 22]],
  [[-78, 8], [-60, 10], [-50, 0], [-35, -6], [-40, -22], [-48, -28], [-58, -38], [-66, -48], [-72, -54], [-74, -40], [-71, -20], [-81, -5], [-78, 8]],
  [[-10, 36], [-9, 44], [-2, 48], [4, 52], [8, 55], [12, 56], [22, 60], [30, 70], [40, 68], [40, 56], [38, 46], [28, 41], [22, 37], [12, 38], [-5, 36], [-10, 36]],
  [[-6, 50], [1, 51], [2, 53], [-2, 58], [-6, 58], [-6, 50]],
  [[-10, 52], [-6, 52], [-6, 55], [-10, 55]],
  [[-17, 21], [-10, 32], [10, 37], [32, 31], [43, 12], [51, 12], [40, -3], [40, -16], [33, -26], [20, -35], [12, -17], [9, 4], [-8, 5], [-17, 14], [-17, 21]],
  [[40, 56], [60, 70], [100, 76], [140, 72], [170, 66], [160, 55], [142, 46], [130, 35], [122, 30], [110, 20], [105, 10], [98, 8], [90, 22], [78, 8], [70, 22], [58, 25], [48, 30], [36, 36], [40, 56]],
  [[114, -22], [130, -12], [142, -11], [153, -26], [146, -39], [135, -35], [115, -34], [114, -22]],
  [[-55, 60], [-20, 70], [-25, 82], [-60, 80], [-55, 60]],
];

function inside(lon: number, lat: number, ring: ReadonlyArray<readonly [number, number]>): boolean {
  let c = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
}

let cache: ReadonlyArray<readonly [number, number]> | null = null;

/** Land sample points ([lon, lat]) on a ~3° grid, computed once. */
export function landDots(): ReadonlyArray<readonly [number, number]> {
  if (cache) return cache;
  const out: Array<readonly [number, number]> = [];
  for (let lat = -80; lat <= 82; lat += 3) {
    const step = 3 / Math.max(0.35, Math.cos((lat * Math.PI) / 180));
    for (let lon = -178; lon <= 178; lon += step) {
      if (LAND.some(ring => inside(lon, lat, ring))) out.push([lon, lat]);
    }
  }
  cache = out;
  return out;
}

export interface Projected {
  readonly x: number;
  readonly y: number;
  readonly visible: boolean;
}

const RAD = Math.PI / 180;

/** Orthographic projection into a 0–100 viewBox, centred on `lon0`, tilted toward `lat0`. */
export function makeProjection(lon0: number, lat0: number, radius = 44) {
  const tilt = Math.max(10, Math.min(40, lat0 * 0.6)) * RAD;
  return (lat: number, lon: number, lift = 1): Projected => {
    const l = (lon - lon0) * RAD;
    const p = lat * RAD;
    const x = Math.cos(p) * Math.sin(l);
    const y = Math.cos(tilt) * Math.sin(p) - Math.sin(tilt) * Math.cos(p) * Math.cos(l);
    const z = Math.sin(tilt) * Math.sin(p) + Math.cos(tilt) * Math.cos(p) * Math.cos(l);
    return { x: 50 + x * radius * lift, y: 50 - y * radius * lift, visible: z > 0 };
  };
}
