import { ICON_SIZE, type IconSize } from '@olympus/brand';
import type { SVGProps } from 'react';

import { cn } from '../utils/cn';

/**
 * SVG renderer for the semantic names owned by `@olympus/brand`.
 *
 * The brand package intentionally owns names and meaning rather than SVG
 * geometry. This module is the one shared place that adapts those names to
 * accessible, inline artwork. It is deliberately not a generic icon font:
 * unknown names use the neutral `unknown` artwork instead of becoming text.
 */
export type IconName = string & {};

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'children' | 'height' | 'role' | 'title' | 'width'> {
  readonly name: IconName;
  readonly size?: IconSize;
  /** Hide an icon that is redundant with adjacent visible text. */
  readonly decorative?: boolean;
  /** Required when a non-decorative icon carries meaning by itself. */
  readonly label?: string;
  readonly title?: string;
}

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

function UnknownArtwork() {
  return <><circle {...stroke} cx="12" cy="12" r="8.5" /><path {...stroke} d="M12 8.25v4.25M12 15.75h.01" /></>;
}

function UserArtwork({ group = false, round = false }: { readonly group?: boolean; readonly round?: boolean }) {
  return (
    <>
      {round && <circle {...stroke} cx="12" cy="12" r="9" />}
      <circle {...stroke} cx={group ? '9' : '12'} cy="8.5" r="3" />
      <path {...stroke} d={group ? 'M3.75 19.25c.6-3.1 2.4-4.75 5.25-4.75s4.65 1.65 5.25 4.75' : 'M5.5 19.25c.75-3.05 2.95-4.75 6.5-4.75s5.75 1.7 6.5 4.75'} />
      {group && <><circle {...stroke} cx="17.5" cy="9.5" r="2.3" /><path {...stroke} d="M15.5 14.9c2.65.15 4.25 1.55 4.75 4.35" /></>}
    </>
  );
}

function DocumentArtwork({ check = false, download = false, upload = false, code = false, pen = false, receipt = false }: {
  readonly check?: boolean;
  readonly download?: boolean;
  readonly upload?: boolean;
  readonly code?: boolean;
  readonly pen?: boolean;
  readonly receipt?: boolean;
}) {
  return (
    <>
      <path {...stroke} d="M7 3.5h6l4 4v13H7z" />
      <path {...stroke} d="M13 3.5v4h4" />
      {check && <path {...stroke} d="m9.25 14 1.8 1.8 3.85-4.1" />}
      {download && <path {...stroke} d="M12 9v6m-2.5-2.5L12 15l2.5-2.5M9 18.5h6" />}
      {upload && <path {...stroke} d="M12 16V10m-2.5 2.5L12 10l2.5 2.5M9 18.5h6" />}
      {code && <path {...stroke} d="m10.5 11-2 2 2 2m3-4 2 2-2 2" />}
      {pen && <path {...stroke} d="m9.3 16.7 1-.25 5.25-5.25-1.3-1.3L9 15.15z" />}
      {receipt && <path {...stroke} d="M9.2 10h5.6M9.2 13h5.6M9.2 16h3.4" />}
    </>
  );
}

function CircleAction({ action }: { readonly action: 'check' | 'x' | 'pause' | 'play' | 'off' | 'stop' | 'help' | 'alert' | 'power' | 'plus' | 'minus' }) {
  const content = {
    check: <path {...stroke} d="m8.4 12.1 2.25 2.25 4.95-5.05" />,
    x: <path {...stroke} d="m9 9 6 6m0-6-6 6" />,
    pause: <path {...stroke} d="M9.25 8.75v6.5m5.5-6.5v6.5" />,
    play: <path {...stroke} d="m10 8.5 5.5 3.5-5.5 3.5z" />,
    off: <path {...stroke} d="M8.5 8.5 15.5 15.5M12 8.5v3.5" />,
    stop: <path {...stroke} d="M9.3 9.3h5.4v5.4H9.3z" />,
    help: <path {...stroke} d="M10.25 10a1.9 1.9 0 1 1 3.25 1.35c-.95.8-1.5 1.2-1.5 2.4m0 2.3h.01" />,
    alert: <><path {...stroke} d="M12 8.3v4.3" /><path {...stroke} d="M12 15.7h.01" /></>,
    power: <><path {...stroke} d="M12 3.75v7" /><path {...stroke} d="M8.1 5.8a7 7 0 1 0 7.8 0" /></>,
    plus: <path {...stroke} d="M12 8.5v7m-3.5-3.5h7" />,
    minus: <path {...stroke} d="M8.5 12h7" />,
  }[action];
  return <><circle {...stroke} cx="12" cy="12" r="8.5" />{content}</>;
}

function ClockArtwork({ state }: { readonly state: 'check' | 'recent' | 'aging' | 'stale' | 'unknown' | 'waiting' }) {
  return (
    <>
      <circle {...stroke} cx="12" cy="12" r="8.5" />
      {state === 'check' && <path {...stroke} d="m8.2 15.8 1.6 1.6 3.8-4" />}
      {state === 'recent' && <path {...stroke} d="M12 7.75v4.5l3 1.75" />}
      {state === 'aging' && <path {...stroke} d="M12 15.5V9m0 0-2.1 2.1M12 9l2.1 2.1" />}
      {state === 'stale' && <><path {...stroke} d="M12 7.75v4.4l2.8 1.8" /><path {...stroke} d="M12 16.6h.01" /></>}
      {state === 'unknown' && <path {...stroke} d="M10.35 10.2a1.8 1.8 0 1 1 3.1 1.25c-.9.75-1.45 1.15-1.45 2.2m0 2h.01" />}
      {state === 'waiting' && <path {...stroke} d="M12 7.75v4.5l-2.5 2" />}
    </>
  );
}

function NavigationArtwork({ name }: { readonly name: string }) {
  switch (name) {
    case 'users-round': return <UserArtwork group />;
    case 'megaphone': return <><path {...stroke} d="M4.5 13.8V9.6l10-3.1v10.4l-10-3.1z" /><path {...stroke} d="m7.6 14.8 1.15 3.2h2.2l-1.1-2.6M17.75 9.4c1 .75 1.5 1.6 1.5 2.6s-.5 1.85-1.5 2.6" /></>;
    case 'network': return <><circle {...stroke} cx="6.5" cy="7" r="2" /><circle {...stroke} cx="17.5" cy="7" r="2" /><circle {...stroke} cx="12" cy="17" r="2" /><path {...stroke} d="m8.15 8.4 2.5 6.15m5.2-6.15-2.5 6.15M8.5 7h7" /></>;
    case 'brain-circuit': return <><path {...stroke} d="M9.4 5.1A3 3 0 0 0 5 7.8c0 .8.3 1.55.8 2.1A3.35 3.35 0 0 0 6.5 16c.75 0 1.4-.25 1.9-.7.45 1.7 1.85 2.9 3.6 2.9s3.15-1.2 3.6-2.9c.5.45 1.15.7 1.9.7a3.35 3.35 0 0 0 .7-6.1A3.1 3.1 0 0 0 14.6 5c-1.1 0-2.05.55-2.6 1.35A3 3 0 0 0 9.4 5.1Z" /><path {...stroke} d="M9 10.5h2l1-2 1.1 5 1-2h1.8" /></>;
    case 'list-checks': return <><path {...stroke} d="M9 6h8m-8 6h8m-8 6h8" /><path {...stroke} d="m4.5 6 1 1 1.5-1.75m-2.5 6 1 1 1.5-1.75m-2.5 6 1 1 1.5-1.75" /></>;
    case 'bell': return <><path {...stroke} d="M7.2 16.1h9.6l-1.15-1.8v-3a3.65 3.65 0 0 0-7.3 0v3z" /><path {...stroke} d="M10.25 18.25c.4.65.95.95 1.75.95s1.35-.3 1.75-.95" /></>;
    case 'settings-2': return <><path {...stroke} d="M5 7h14M5 17h14" /><circle {...stroke} cx="9" cy="7" r="2" /><circle {...stroke} cx="15" cy="17" r="2" /></>;
    case 'receipt-text': return <DocumentArtwork receipt />;
    case 'circle-user-round': return <UserArtwork round />;
    case 'file-check-2': return <DocumentArtwork check />;
    case 'chart-no-axes-combined': return <><path {...stroke} d="m5 16 4-4 3 2 6-7" /><path {...stroke} d="M16.5 7H18v1.5" /><path {...stroke} d="M5 19h14" /></>;
    case 'shield-check': return <><path {...stroke} d="M12 3.5 18 6v4.3c0 4.1-2.4 6.85-6 8.2-3.6-1.35-6-4.1-6-8.2V6z" /><path {...stroke} d="m9.25 11.8 1.75 1.75 3.8-3.85" /></>;
    case 'activity-square': return <><rect {...stroke} x="4.5" y="4.5" width="15" height="15" rx="2" /><path {...stroke} d="M6.8 12h2.35l1.4-3.2 2.7 6.4 1.45-3.2h2.5" /></>;
    case 'badge-check': return <><path {...stroke} d="m12 3.7 1.75 1.15 2.05-.2.75 1.9 1.75 1.1-.75 1.9.25 2.05-1.7 1.15-.75 1.9-2.05-.2L12 17.6l-1.75-1.15-2.05.2-.75-1.9-1.75-1.15.75-1.9-.25-2.05 1.7-1.15.75-1.9 2.05.2z" /><path {...stroke} d="m9.25 11.8 1.75 1.75 3.8-3.85" /></>;
    case 'plug-zap': return <><path {...stroke} d="M8 8.5v-3m4 3v-3m-5.5 6h7v1.3a4 4 0 0 1-4 4h-1a4 4 0 0 1-4-4zM10 16.8V20" /><path {...stroke} d="m16.5 6.2-2 3h2.25L15 12.8" /></>;
    case 'file-up': return <DocumentArtwork upload />;
    case 'rocket': return <><path {...stroke} d="M13.2 5.05c2.5-1.2 4.8-1.25 5.7-1.15.1.9.05 3.2-1.15 5.7L11 16.3l-3.3-3.3z" /><path {...stroke} d="m10.1 8.1-3.6.45-1.4 3.4 2.65.65m5.5 1.35.65 2.65 3.4-1.4.45-3.6M8.4 15.6l-2.85 2.85M12.8 8.9h.01" /></>;
    case 'credit-card': return <><rect {...stroke} x="3.5" y="6" width="17" height="12" rx="2" /><path {...stroke} d="M3.5 10h17M7 14h3" /></>;
    case 'gauge': return <><path {...stroke} d="M5.3 16a7.5 7.5 0 1 1 13.4 0" /><path {...stroke} d="m12 12 3.5-2.5M7.6 16h8.8" /></>;
    case 'circle-power': return <CircleAction action="power" />;
    case 'route': return <><circle {...stroke} cx="6.5" cy="17.5" r="1.8" /><circle {...stroke} cx="17.5" cy="6.5" r="1.8" /><path {...stroke} d="M8.3 17.5h3.2a3 3 0 0 0 3-3v-5a3 3 0 0 1 3-3" /></>;
    case 'radar': return <><circle {...stroke} cx="12" cy="12" r="7.5" /><path {...stroke} d="M12 4.5v7.5l5.3 5.3M8.2 12a3.8 3.8 0 0 1 3.8-3.8" /></>;
    case 'award': return <><circle {...stroke} cx="12" cy="9" r="4.8" /><path {...stroke} d="m8.7 12.5-1 7 4.3-2.15 4.3 2.15-1-7" /></>;
    case 'send': return <><path {...stroke} d="m4 4.5 16 7.5L4 19.5l2.2-6.1z" /><path {...stroke} d="M6.2 13.4H13" /></>;
    case 'coins': return <><ellipse {...stroke} cx="10" cy="7" rx="4.5" ry="2.2" /><path {...stroke} d="M5.5 7v5.2c0 1.2 2 2.2 4.5 2.2s4.5-1 4.5-2.2V7m1.5 3.3c1.7.2 3 .95 3 1.85v4.2c0 1.2-2 2.2-4.5 2.2-1 0-1.9-.15-2.6-.45" /></>;
    case 'chart-candlestick': return <><path {...stroke} d="M6.5 5v14m0-10h3v5h-3m5.5-10v16m0-11h3v6h-3m5.5-6v10m0-7h3v4h-3" /></>;
    case 'bot-key': return <><rect {...stroke} x="5" y="6.5" width="10" height="8.5" rx="2" /><path {...stroke} d="M10 4v2.5m-2.5 4h.01m5 0h.01M7.5 15v2h5v-2" /><circle {...stroke} cx="18" cy="15.5" r="2" /><path {...stroke} d="M19.5 17 21 18.5m-1-.5 1-1" /></>;
    case 'waypoints': return <><circle {...stroke} cx="6" cy="17" r="2" /><circle {...stroke} cx="12" cy="7" r="2" /><circle {...stroke} cx="18" cy="15" r="2" /><path {...stroke} d="m7.1 15.3 3.8-6.55m2.1.85 3.9 3.9" /></>;
    case 'crosshair': return <><circle {...stroke} cx="12" cy="12" r="5" /><path {...stroke} d="M12 3v3m0 12v3M3 12h3m12 0h3M12 10.5v3m-1.5-1.5h3" /></>;
    case 'git-fork': return <><circle {...stroke} cx="7" cy="5.5" r="1.8" /><circle {...stroke} cx="17" cy="5.5" r="1.8" /><circle {...stroke} cx="12" cy="18.5" r="1.8" /><path {...stroke} d="M7 7.3v2.1a3 3 0 0 0 3 3h2a3 3 0 0 1 3 3v1.3M12 12.4V15a3 3 0 0 1-3 3H7" /></>;
    case 'panels-top-left': return <><rect {...stroke} x="4" y="4" width="16" height="16" rx="2" /><path {...stroke} d="M4 9h16M10 9v11" /></>;
    case 'siren': return <><path {...stroke} d="M7.5 16v-3.5a4.5 4.5 0 0 1 9 0V16zM5.5 16h13M12 5V3.5m-5.4 3L5.5 5.4m12 1.1 1.1-1.1" /></>;
    case 'terminal-square': return <><rect {...stroke} x="4" y="4" width="16" height="16" rx="2" /><path {...stroke} d="m7.5 9 2.5 2.5L7.5 14M12.5 14h4" /></>;
    case 'radio-tower': return <><path {...stroke} d="M12 7v12m-3.5 0 3.5-8 3.5 8M8 19h8M6.2 6.2a8.2 8.2 0 0 0 0 11.6m11.6-11.6a8.2 8.2 0 0 1 0 11.6" /></>;
    case 'command': return <><path {...stroke} d="M8.2 8.2h7.6v7.6H8.2z" /><path {...stroke} d="M8.2 11.2H6.1a2.1 2.1 0 1 1 0-4.2h2.1m7.6 4.2h2.1a2.1 2.1 0 1 1 0 4.2h-2.1M11.2 8.2V6.1a2.1 2.1 0 1 1 4.2 0v2.1m-4.2 7.6v2.1a2.1 2.1 0 1 1-4.2 0v-2.1" /></>;
    case 'clipboard-check': return <><path {...stroke} d="M8 5.5h8v14H8zM10 5.5V4h4v1.5" /><path {...stroke} d="m10.1 12 1.55 1.55 3-3.15" /></>;
    case 'boxes': return <><path {...stroke} d="m5 8 4-2.2L13 8 9 10.2zM13 8l4-2.2L21 8l-4 2.2zM9 10.2v4.6L5 17v-4.6m8-2.2v4.6l4 2.2v-4.6" /></>;
    case 'sparkles': return <><path {...stroke} d="m12 3.8.85 4.35L17 9l-4.15.85L12 14.2l-.85-4.35L7 9l4.15-.85zM18.2 14.2l.45 2.25 2.2.45-2.2.45-.45 2.25-.45-2.25-2.2-.45 2.2-.45z" /></>;
    case 'building-2': return <><path {...stroke} d="M5 20V5h10v15m0-10h4v10M8 8h1m3 0h1M8 12h1m3 0h1M8 16h1m3 0h1M3.5 20h17" /></>;
    case 'database-zap': return <><ellipse {...stroke} cx="10" cy="6.5" rx="5" ry="2.4" /><path {...stroke} d="M5 6.5v7c0 1.3 2.25 2.4 5 2.4.7 0 1.35-.05 1.95-.18M15 6.5v5.25" /><path {...stroke} d="m17.5 12-2 3h2.35l-1.2 3" /></>;
    case 'clipboard-list': return <><path {...stroke} d="M8 5.5h8v14H8zM10 5.5V4h4v1.5" /><path {...stroke} d="M10.5 10h3.5m-3.5 3h3.5m-3.5 3h3.5" /></>;
    case 'search-check': return <><circle {...stroke} cx="10.5" cy="10.5" r="5" /><path {...stroke} d="m14.2 14.2 4.3 4.3m-10-7 1.5 1.5 2.8-3" /></>;
    case 'scan-search': return <><path {...stroke} d="M7 5H5v3m12-3h2v3M7 19H5v-3m14 0v3h-2" /><circle {...stroke} cx="11" cy="11" r="3.25" /><path {...stroke} d="m13.5 13.5 3.5 3.5" /></>;
    case 'package-check': return <><path {...stroke} d="m5 8 7-4 7 4v8l-7 4-7-4zM5 8l7 4 7-4M12 12v8" /><path {...stroke} d="m9.7 14.9 1.4 1.4 2.8-3" /></>;
    case 'clipboard-signature': return <><path {...stroke} d="M8 5.5h8v14H8zM10 5.5V4h4v1.5" /><path {...stroke} d="M10 15.5c.8-1.55 1.45-1.85 1.95-.9.4.8.85.7 1.4-.3.5-.9 1-.8 1.65.2M10 11h4" /></>;
    case 'heart-pulse': return <><path {...stroke} d="M4.5 12h3l1.35-3 2.3 6 1.65-4h2.7l1.25 1.5h2.8" /><path {...stroke} d="M19 7.4a4.1 4.1 0 0 0-6.25-.5L12 7.65l-.75-.75A4.1 4.1 0 0 0 5.5 12.7L12 19l5.1-4.95" /></>;
    case 'map-pinned': return <><path {...stroke} d="M4.5 6.5 9 4l6 2.5L19.5 4v13.5L15 20l-6-2.5-4.5 2.5zM9 4v13.5m6-11v13.5" /><path {...stroke} d="M15 9a2 2 0 1 0-4 0c0 1.5 2 3.5 2 3.5S15 10.5 15 9Z" /></>;
    case 'circle-gauge': return <><circle {...stroke} cx="12" cy="12" r="8.5" /><path {...stroke} d="m8.4 14.5 3.6-4 3.6 2M8.3 16h7.4" /></>;
    case 'lightbulb': return <><path {...stroke} d="M8.5 14.8A5 5 0 1 1 15.5 14.8c-.8.65-1.2 1.25-1.35 2.2h-4.3c-.15-.95-.55-1.55-1.35-2.2ZM10.2 20h3.6M10 17h4" /></>;
    case 'braces': return <><path {...stroke} d="M9 5.5H7.8A1.8 1.8 0 0 0 6 7.3v2.2c0 1.1-.55 1.7-1.5 2.5.95.8 1.5 1.4 1.5 2.5v2.2a1.8 1.8 0 0 0 1.8 1.8H9m6-13H16.2A1.8 1.8 0 0 0 14.4 7.3v2.2c0 1.1.55 1.7 1.5 2.5-.95.8-1.5 1.4-1.5 2.5v2.2a1.8 1.8 0 0 0 1.8 1.8H15" /></>;
    case 'traffic-cone': return <><path {...stroke} d="m9 5 6 12H9L6 21h12l-3-4h-5l2-4H8z" /><path {...stroke} d="M8.5 11h7" /></>;
    case 'cable': return <><path {...stroke} d="M8 6V4m4 2V4m-5 5h6v2.5a4 4 0 0 1-4 4H8a3 3 0 0 0-3 3V20m5-4v4" /></>;
    case 'cpu': return <><rect {...stroke} x="7" y="7" width="10" height="10" rx="1.5" /><path {...stroke} d="M9 3.8V7m3-3.2V7m3-3.2V7M9 17v3.2m3-3.2v3.2m3-3.2v3.2M3.8 9H7m-3.2 3H7m-3.2 3H7m10-6h3.2m-3.2 3h3.2m-3.2 3h3.2" /></>;
    case 'landmark': return <><path {...stroke} d="m4 9 8-4 8 4M5.5 10.5h13M6.5 10.5v6m3.7-6v6m3.6-6v6m3.7-6v6M4 19h16" /></>;
    case 'badge-dollar-sign': return <><circle {...stroke} cx="12" cy="12" r="8" /><path {...stroke} d="M12 7.5v9m2.25-6.55c-.35-.8-1.1-1.2-2.25-1.2-1.3 0-2.1.6-2.1 1.55 0 2.4 4.35.75 4.35 3.2 0 1-.8 1.65-2.25 1.65-1.15 0-1.95-.45-2.35-1.3" /></>;
    case 'focus': return <><circle {...stroke} cx="12" cy="12" r="4" /><path {...stroke} d="M12 4v2m0 12v2M4 12h2m12 0h2" /></>;
    case 'database-backup': return <><ellipse {...stroke} cx="12" cy="6.5" rx="6" ry="2.5" /><path {...stroke} d="M6 6.5v8c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-8" /><path {...stroke} d="M9.5 19.5h7m-2.5-2.5 2.5 2.5-2.5 2.5" /></>;
    case 'hand-coins': return <><path {...stroke} d="M4.5 15.5h3l2-2h4c1.5 0 2.5.65 2.5 1.6 0 .9-.8 1.4-2.5 1.4h-2M4.5 15.5v3.2h4.2l5.8-2.2M15.8 9.2a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6Zm0-3.3v2" /></>;
    case 'badge-percent': return <><circle {...stroke} cx="12" cy="12" r="8" /><path {...stroke} d="m9 15 6-6M9.4 9.4h.01m5.2 5.2h.01" /></>;
    case 'tags': return <><path {...stroke} d="M4.5 5.5h7l7.5 7.5-6 6-7.5-7.5z" /><circle {...stroke} cx="8.5" cy="9.5" r="1" /></>;
    case 'folder-kanban': return <><path {...stroke} d="M4 7h6l1.5 1.5H20v10H4z" /><path {...stroke} d="M8 11v4m4-4v2m4-2v4" /></>;
    case 'contact-round': return <><rect {...stroke} x="4" y="5" width="16" height="14" rx="2" /><circle {...stroke} cx="9" cy="10" r="2" /><path {...stroke} d="M6.5 16c.45-1.7 1.25-2.5 2.5-2.5s2.05.8 2.5 2.5m3-5h2.5m-2.5 3h2.5" /></>;
    case 'calculator': return <><rect {...stroke} x="6" y="4" width="12" height="16" rx="2" /><path {...stroke} d="M8.5 7.5h7m-7 4h1m3 0h1m-6 3h1m3 0h1m3-3h1m0 3h1" /></>;
    case 'fingerprint-pattern': return <><path {...stroke} d="M8 10a4 4 0 1 1 8 0c0 4.7-1.25 7.5-2.2 9M5.8 9.5A6.2 6.2 0 0 1 18.2 9.5c0 3.25-.55 6.8-1.55 9.5M10 13c0 2.6-.35 4.5-.9 6M13.5 13c0 1.55-.15 3-.45 4.3" /></>;
    case 'workflow': return <><rect {...stroke} x="4" y="5" width="5" height="4" rx="1" /><rect {...stroke} x="15" y="5" width="5" height="4" rx="1" /><rect {...stroke} x="9.5" y="15" width="5" height="4" rx="1" /><path {...stroke} d="M9 7h6m-3 2v6" /></>;
    case 'shield-alert': return <><path {...stroke} d="M12 3.5 18 6v4.3c0 4.1-2.4 6.85-6 8.2-3.6-1.35-6-4.1-6-8.2V6z" /><path {...stroke} d="M12 8.5v4m0 2.8h.01" /></>;
    case 'stethoscope': return <><path {...stroke} d="M7 5v4.5a3.5 3.5 0 0 0 7 0V5m-7 0h2m3 0h2m-2.5 8.4V15a3.2 3.2 0 0 0 6.4 0v-1.5" /><circle {...stroke} cx="18" cy="12.5" r="1.5" /></>;
    case 'flask-conical': return <><path {...stroke} d="M9 4h6m-4 0v5.3l-4.3 7.25A2 2 0 0 0 8.4 19h7.2a2 2 0 0 0 1.7-2.45L13 9.3V4" /><path {...stroke} d="M8.5 15h7" /></>;
    default: return undefined;
  }
}

function GeneralArtwork({ name }: { readonly name: string }) {
  switch (name) {
    case 'connect':
    case 'plug': return <><path {...stroke} d="M8 8.5v-3m4 3v-3m-5.5 6h7v1.3a4 4 0 0 1-4 4h-1a4 4 0 0 1-4-4zM10 16.8V20" /></>;
    case 'configure':
    case 'sliders-horizontal': return <><path {...stroke} d="M5 7h14M5 12h14M5 17h14" /><circle {...stroke} cx="9" cy="7" r="1.6" /><circle {...stroke} cx="15" cy="12" r="1.6" /><circle {...stroke} cx="11" cy="17" r="1.6" /></>;
    case 'retry':
    case 'rotate-cw':
    case 'refresh-cw': return <><path {...stroke} d="M18 10a6.5 6.5 0 0 0-11-2L5.5 9.5M6 14a6.5 6.5 0 0 0 11 2l1.5-1.5" /><path {...stroke} d="M5.5 6.5v3H8.5m10-1v3H15.5" /></>;
    case 'search': return <><circle {...stroke} cx="10.5" cy="10.5" r="5.25" /><path {...stroke} d="m14.3 14.3 4.2 4.2" /></>;
    case 'circle-check': return <CircleAction action="check" />;
    case 'circle-x': return <CircleAction action="x" />;
    case 'circle-pause': return <CircleAction action="pause" />;
    case 'circle-play': return <CircleAction action="play" />;
    case 'file-down': return <DocumentArtwork download />;
    case 'signal-high': return <><path {...stroke} d="M5 18h2.5v-3H5zm4.5 0H12v-6H9.5zm4.5 0h2.5V9H14zm4.5 0H21V5h-2.5z" /></>;
    case 'signal-medium': return <><path {...stroke} d="M5 18h2.5v-3H5zm4.5 0H12v-6H9.5zm4.5 0h2.5V9H14z" /></>;
    case 'signal-low': return <><path {...stroke} d="M5 18h2.5v-3H5z" /></>;
    case 'circle-help': return <CircleAction action="help" />;
    case 'fingerprint': return <><path {...stroke} d="M8 10a4 4 0 1 1 8 0c0 4.7-1.25 7.5-2.2 9M5.8 9.5A6.2 6.2 0 0 1 18.2 9.5c0 3.25-.55 6.8-1.55 9.5M10 13c0 2.6-.35 4.5-.9 6M13.5 13c0 1.55-.15 3-.45 4.3" /></>;
    case 'shopping-cart': return <><path {...stroke} d="M4 5h2l1.7 9.2h8.8l1.5-6.5H7" /><circle {...stroke} cx="9" cy="18" r="1" /><circle {...stroke} cx="16" cy="18" r="1" /></>;
    case 'banknote': return <><rect {...stroke} x="4" y="7" width="16" height="10" rx="1.5" /><circle {...stroke} cx="12" cy="12" r="2" /><path {...stroke} d="M7 10h.01M17 14h.01" /></>;
    case 'shield': return <path {...stroke} d="M12 3.5 18 6v4.3c0 4.1-2.4 6.85-6 8.2-3.6-1.35-6-4.1-6-8.2V6z" />;
    case 'brain': return <><path {...stroke} d="M9.4 5.1A3 3 0 0 0 5 7.8c0 .8.3 1.55.8 2.1A3.35 3.35 0 0 0 6.5 16c.75 0 1.4-.25 1.9-.7.45 1.7 1.85 2.9 3.6 2.9s3.15-1.2 3.6-2.9c.5.45 1.15.7 1.9.7a3.35 3.35 0 0 0 .7-6.1A3.1 3.1 0 0 0 14.6 5c-1.1 0-2.05.55-2.6 1.35A3 3 0 0 0 9.4 5.1Z" /><path {...stroke} d="M12 7.25v9.5M8.2 10.2H12m0 3.6h3.8" /></>;
    case 'wrench': return <><path {...stroke} d="M14.6 6.1a4 4 0 0 0-5.2 5.2L4.8 15.9a1.7 1.7 0 0 0 2.4 2.4l4.6-4.6a4 4 0 0 0 5.2-5.2l-2.5 2.1-2.1-2.1z" /></>;
    case 'database': return <><ellipse {...stroke} cx="12" cy="6.5" rx="6" ry="2.5" /><path {...stroke} d="M6 6.5v8c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-8M6 10.5c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" /></>;
    case 'user-round': return <UserArtwork />;
    case 'bot': return <><rect {...stroke} x="5" y="6.5" width="14" height="10" rx="2" /><path {...stroke} d="M12 4v2.5m-4 4h.01m8 0h.01M8 14h8M9 16.5v2m6-2v2" /></>;
    case 'wallet-cards': return <><rect {...stroke} x="5" y="6" width="14" height="12" rx="2" /><path {...stroke} d="M5 9h14m-4 4h3" /></>;
    case 'smartphone': return <><rect {...stroke} x="7.5" y="3.5" width="9" height="17" rx="1.8" /><path {...stroke} d="M10.5 6h3m-1.5 11.5h.01" /></>;
    case 'file-code-2': return <DocumentArtwork code />;
    case 'share-2': return <><circle {...stroke} cx="6" cy="12" r="2" /><circle {...stroke} cx="17.5" cy="6.5" r="2" /><circle {...stroke} cx="17.5" cy="17.5" r="2" /><path {...stroke} d="m7.8 11.1 7.8-3.7m-7.8 5.8 7.8 3.7" /></>;
    case 'key-round': return <><circle {...stroke} cx="8.5" cy="12" r="3.5" /><path {...stroke} d="m11.5 12 7 0m-2 0v2m-2-2v2" /></>;
    case 'arrow-left-right': return <><path {...stroke} d="M5 8h13m0 0-2.5-2.5M18 8l-2.5 2.5M19 16H6m0 0 2.5-2.5M6 16l2.5 2.5" /></>;
    case 'messages-square': return <><path {...stroke} d="M4.5 5.5h10v8H9l-3.5 3v-3H4.5zM15.5 9.5h4v8h-1v3l-3.5-3h-3" /></>;
    case 'app-window': return <><rect {...stroke} x="4" y="5" width="16" height="14" rx="2" /><path {...stroke} d="M4 9h16M7 7h.01m2 0h.01" /></>;
    case 'shopping-bag': return <><path {...stroke} d="M5.5 8h13l-1 11h-11zM9 8a3 3 0 0 1 6 0" /></>;
    case 'blocks': return <><path {...stroke} d="m7 5 5 3-5 3-5-3zm10 0 5 3-5 3-5-3zM12 13l5 3-5 3-5-3z" /></>;
    case 'newspaper': return <><path {...stroke} d="M5 5h13v14H5zM8 8h7M8 11h7M8 14h4" /><path {...stroke} d="M18 8h1v9a2 2 0 0 1-2 2H7" /></>;
    case 'clock-check': return <ClockArtwork state="check" />;
    case 'clock-4': return <ClockArtwork state="recent" />;
    case 'clock-arrow-up': return <ClockArtwork state="aging" />;
    case 'clock-alert': return <ClockArtwork state="stale" />;
    case 'clock-question-mark': return <ClockArtwork state="unknown" />;
    case 'user-round-check': return <><UserArtwork /><path {...stroke} d="m16.3 16.6 1.25 1.25 2.3-2.4" /></>;
    case 'git-branch': return <><circle {...stroke} cx="7" cy="5.5" r="1.7" /><circle {...stroke} cx="17" cy="18.5" r="1.7" /><circle {...stroke} cx="17" cy="5.5" r="1.7" /><path {...stroke} d="M7 7.2v5.3a3 3 0 0 0 3 3h5.3M10 12.5h2a3 3 0 0 0 3-3V7.2" /></>;
    case 'file-pen-line': return <DocumentArtwork pen />;
    case 'octagon-alert': return <><path {...stroke} d="m8 3.8h8l4.2 4.2v8L16 20.2H8L3.8 16V8z" /><path {...stroke} d="M12 8.3v4.4m0 3h.01" /></>;
    case 'triangle-alert': return <><path {...stroke} d="m12 4 8 15H4z" /><path {...stroke} d="M12 9v4m0 2.75h.01" /></>;
    case 'circle-alert': return <CircleAction action="alert" />;
    case 'info': return <><circle {...stroke} cx="12" cy="12" r="8.5" /><path {...stroke} d="M12 10.75v5m0-8h.01" /></>;
    case 'message-circle-more': return <><path {...stroke} d="M19 11.5a7 7 0 1 1-12.75-4l-1.1-2.3 2.8.5A7 7 0 0 1 19 11.5Z" /><path {...stroke} d="M9 11.5h.01m3 0h.01m3 0h.01" /></>;
    case 'circle-off': return <CircleAction action="off" />;
    case 'ban': return <><circle {...stroke} cx="12" cy="12" r="8.5" /><path {...stroke} d="m6 6 12 12" /></>;
    case 'package-x': return <><path {...stroke} d="m5 8 7-4 7 4v8l-7 4-7-4zM5 8l7 4 7-4M12 12v8" /><path {...stroke} d="m15 12 3 3m0-3-3 3" /></>;
    case 'lock-keyhole': return <><rect {...stroke} x="6" y="10" width="12" height="9" rx="1.5" /><path {...stroke} d="M8.5 10V8a3.5 3.5 0 0 1 7 0v2m-3.5 3v3" /></>;
    case 'circle-stop': return <CircleAction action="stop" />;
    case 'key-x': return <><circle {...stroke} cx="8.5" cy="12" r="3.5" /><path {...stroke} d="m11.5 12 7 0m-2-2 3 3m0-3-3 3" /></>;
    case 'loader-circle': return <><path {...stroke} d="M18.5 12a6.5 6.5 0 1 1-2-4.65" /><path {...stroke} d="M16.5 5.2v3h-3" /></>;
    case 'clock-3': return <ClockArtwork state="waiting" />;
    case 'history': return <><path {...stroke} d="M5.5 8.5A7.5 7.5 0 1 1 4.5 12H2.8m0 0 2.2-2.2M2.8 12 5 14.2" /><path {...stroke} d="M12 7.5v4.75l3 1.75" /></>;
    case 'circle-check-big': return <CircleAction action="check" />;
    case 'pie-chart': return <><path {...stroke} d="M12 4v8h8A8 8 0 0 0 12 4Z" /><path {...stroke} d="M10 5.3A7 7 0 1 0 18.7 14H10z" /></>;
    case 'octagon-x': return <><path {...stroke} d="m8 3.8h8l4.2 4.2v8L16 20.2H8L3.8 16V8z" /><path {...stroke} d="m9 9 6 6m0-6-6 6" /></>;
    // Controlled legacy aliases used by the deprecated GlyphIcon adapter.
    case 'copy': return <><rect {...stroke} x="8" y="8" width="9" height="10" rx="1" /><path {...stroke} d="M6 15V6a1 1 0 0 1 1-1h7" /></>;
    case 'arrow-right': return <path {...stroke} d="M5 12h13m-4-4 4 4-4 4" />;
    case 'save': return <><path {...stroke} d="M5 4h12l2 2v14H5z" /><path {...stroke} d="M8 4v5h7V4m-7 13h8" /></>;
    case 'circle-plus': return <CircleAction action="plus" />;
    case 'circle-minus': return <CircleAction action="minus" />;
    default: return undefined;
  }
}

/** True only for a renderer-supported, named brand icon. Useful for tests and migration diagnostics. */
export function hasIconArtwork(name: string): boolean {
  return Boolean(NavigationArtwork({ name }) ?? GeneralArtwork({ name }));
}

export function Icon({
  name,
  size = 'md',
  decorative,
  label,
  title,
  className,
  ...svgProps
}: IconProps) {
  const accessibleName = label ?? title ?? name.replace(/[-_]+/g, ' ');
  const isDecorative = decorative ?? !(label ?? title);
  const artwork = NavigationArtwork({ name }) ?? GeneralArtwork({ name }) ?? <UnknownArtwork />;
  const pixelSize = ICON_SIZE[size];

  return (
    <svg
      {...svgProps}
      viewBox="0 0 24 24"
      width={pixelSize}
      height={pixelSize}
      className={cn('aether-icon inline-block shrink-0 align-middle', className)}
      focusable="false"
      {...(isDecorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': accessibleName })}
    >
      {!isDecorative && <title>{accessibleName}</title>}
      {artwork}
    </svg>
  );
}
