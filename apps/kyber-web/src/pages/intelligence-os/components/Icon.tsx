import type { NodeKind } from '../lib/kyber'

type IconName = NodeKind | 'search' | 'settings' | 'chevron' | 'arrow' | 'close' | 'play' | 'pause' | 'command' | 'plus' | 'check' | 'lock' | 'pulse' | 'calendar' | 'spark' | 'more' | 'filter' | 'fullscreen' | 'pin' | 'layers' | 'clock' | 'external' | 'menu'

type IconProps = {
  name: IconName
  size?: number
  className?: string
  strokeWidth?: number
}

export function Icon({ name, size = 16, className = '', strokeWidth = 1.5 }: IconProps) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

  const shape = (() => {
    switch (name) {
      case 'human':
        return <><circle cx="12" cy="7" r="3" {...common} /><path d="M5.5 20c.5-3.4 2.6-5.1 6.5-5.1s6 1.7 6.5 5.1" {...common} /></>
      case 'organization':
        return <><path d="M5 20V5.5L12 3l7 2.5V20" {...common} /><path d="M8 9h1M15 9h1M8 13h1M15 13h1M11 20v-4h2v4" {...common} /></>
      case 'agent':
        return <><rect x="4" y="5" width="16" height="14" rx="4" {...common} /><path d="M8 11h.01M16 11h.01M8.5 15c1.7 1.3 5.3 1.3 7 0M12 5V2M9.5 2h5" {...common} /></>
      case 'campaign':
        return <><path d="m4 12 12-5v10L4 12Z" {...common} /><path d="M16 10.5c2.6.3 4 1.1 4 1.5s-1.4 1.2-4 1.5M7 14.2 8.3 20h2.4l-1.1-4.8" {...common} /></>
      case 'cluster':
        return <><circle cx="12" cy="12" r="3" {...common} /><circle cx="5" cy="7" r="2" {...common} /><circle cx="19" cy="7" r="2" {...common} /><circle cx="6" cy="18" r="2" {...common} /><circle cx="18" cy="18" r="2" {...common} /><path d="m7 8.4 2.8 2M17 8.4 14.2 11M8 17l2-2.4M16 17l-2-2.4" {...common} /></>
      case 'journey':
        return <><path d="M4 18c3.3-8.7 6.3-8.7 9.3-2.3C15.8 21 18 18.5 20 12" {...common} /><circle cx="4" cy="18" r="1.5" {...common} /><circle cx="20" cy="12" r="1.5" {...common} /></>
      case 'system':
        return <><rect x="5" y="5" width="14" height="14" rx="2" {...common} /><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" {...common} /></>
      case 'search':
        return <><circle cx="10.8" cy="10.8" r="6" {...common} /><path d="m16 16 4.3 4.3" {...common} /></>
      case 'settings':
        return <><circle cx="12" cy="12" r="2.8" {...common} /><path d="M19.2 15a1.6 1.6 0 0 0 .3 1.8l.1.1-1.8 1.8-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2h-2.6v-.2a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1-1.8-1.8.1-.1A1.6 1.6 0 0 0 8 15a1.6 1.6 0 0 0-1.5-1H6.3v-2.6h.2a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1 1.8-1.8.1.1a1.6 1.6 0 0 0 1.8.3 1.6 1.6 0 0 0 1-1.5v-.2h2.6v.2a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1 1.8 1.8-.1.1a1.6 1.6 0 0 0-.3 1.8 1.6 1.6 0 0 0 1.5 1h.2V14h-.2a1.6 1.6 0 0 0-1.5 1Z" {...common} /></>
      case 'chevron':
        return <path d="m8 10 4 4 4-4" {...common} />
      case 'arrow':
        return <path d="M4 12h15m-5-5 5 5-5 5" {...common} />
      case 'close':
        return <path d="m7 7 10 10M17 7 7 17" {...common} />
      case 'play':
        return <path d="m9 6 8 6-8 6V6Z" {...common} />
      case 'pause':
        return <path d="M9 6v12M15 6v12" {...common} />
      case 'command':
        return <><path d="M9 9V6a3 3 0 1 0-3 3h3ZM15 9V6a3 3 0 1 1 3 3h-3ZM9 15v3a3 3 0 1 1-3-3h3ZM15 15v3a3 3 0 1 0 3-3h-3ZM9 9h6v6H9z" {...common} /></>
      case 'plus':
        return <path d="M12 5v14M5 12h14" {...common} />
      case 'check':
        return <path d="m5 12 4.3 4.3L19 7" {...common} />
      case 'lock':
        return <><rect x="5" y="10" width="14" height="10" rx="2" {...common} /><path d="M8 10V7a4 4 0 0 1 8 0v3" {...common} /></>
      case 'pulse':
        return <path d="M3 12h3l2-5 4 10 2.2-5H21" {...common} />
      case 'calendar':
        return <><rect x="4" y="5" width="16" height="15" rx="2" {...common} /><path d="M8 3v4M16 3v4M4 10h16" {...common} /></>
      case 'spark':
        return <><path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5L12 3ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" {...common} /></>
      case 'more':
        return <><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></>
      case 'filter':
        return <path d="M4 6h16M7 12h10M10 18h4" {...common} />
      case 'fullscreen':
        return <><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" {...common} /></>
      case 'pin':
        return <><path d="m8 4 8 8M9 3 21 15l-3 1-3 3-1 3L3 11l3-1 3-3Z" {...common} /><path d="m12 12-8 8" {...common} /></>
      case 'layers':
        return <><path d="m12 4 8 4-8 4-8-4 8-4Z" {...common} /><path d="m4 12 8 4 8-4M4 16l8 4 8-4" {...common} /></>
      case 'clock':
        return <><circle cx="12" cy="12" r="8" {...common} /><path d="M12 7v5l3 2" {...common} /></>
      case 'external':
        return <><path d="M14 5h5v5M19 5l-8 8" {...common} /><path d="M18 13v5H6V6h5" {...common} /></>
      case 'menu':
        return <path d="M4 7h16M4 12h16M4 17h16" {...common} />
      default:
        return <circle cx="12" cy="12" r="7" {...common} />
    }
  })()

  return <svg aria-hidden="true" className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" role="presentation">{shape}</svg>
}
