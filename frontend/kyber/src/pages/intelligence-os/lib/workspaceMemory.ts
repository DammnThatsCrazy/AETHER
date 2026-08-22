export type WorkspaceMemory = {
  selectedId: string
  activeNav: string
  activeStage: string
  evidenceMode: boolean
  beforeAfter: boolean
  timeline: number
  zoomLevel: number
  authority: string
  actionState: string
  investigationStatus: string
  saved: boolean
  investigationNote: string
}

const STORAGE_KEY = 'kyber.intelligence.workspace.v1'

const isBoolean = (value: unknown): value is boolean => typeof value === 'boolean'
const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const isString = (value: unknown): value is string => typeof value === 'string'

export function readWorkspaceMemory(): Partial<WorkspaceMemory> {
  if (typeof window === 'undefined') return {}

  let stored: Partial<WorkspaceMemory> = {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, unknown>
      stored = {
        ...(isString(parsed.selectedId) ? { selectedId: parsed.selectedId } : {}),
        ...(isString(parsed.activeNav) ? { activeNav: parsed.activeNav } : {}),
        ...(isString(parsed.activeStage) ? { activeStage: parsed.activeStage } : {}),
        ...(isBoolean(parsed.evidenceMode) ? { evidenceMode: parsed.evidenceMode } : {}),
        ...(isBoolean(parsed.beforeAfter) ? { beforeAfter: parsed.beforeAfter } : {}),
        ...(isNumber(parsed.timeline) ? { timeline: Math.max(0, Math.min(100, parsed.timeline)) } : {}),
        ...(isNumber(parsed.zoomLevel) ? { zoomLevel: Math.max(1, Math.min(5, parsed.zoomLevel)) } : {}),
        ...(isString(parsed.authority) ? { authority: parsed.authority } : {}),
        ...(isString(parsed.actionState) ? { actionState: parsed.actionState } : {}),
        ...(isString(parsed.investigationStatus) ? { investigationStatus: parsed.investigationStatus } : {}),
        ...(isBoolean(parsed.saved) ? { saved: parsed.saved } : {}),
        ...(isString(parsed.investigationNote) ? { investigationNote: parsed.investigationNote } : {}),
      }
    }
  } catch {
    stored = {}
  }

  const params = new URLSearchParams(window.location.search)
  return {
    ...stored,
    ...(params.get('entity') ? { selectedId: params.get('entity') as string } : {}),
    ...(params.get('view') ? { activeNav: params.get('view') as string } : {}),
    ...(params.get('stage') ? { activeStage: params.get('stage') as string } : {}),
    ...(params.get('evidence') === '1' ? { evidenceMode: true } : {}),
    ...(params.get('compare') === '1' ? { beforeAfter: true } : {}),
    ...(params.get('time') ? { timeline: Math.max(0, Math.min(100, Number(params.get('time')) || 78)) } : {}),
    ...(params.get('zoom') ? { zoomLevel: Math.max(1, Math.min(5, Number(params.get('zoom')) || 3)) } : {}),
  }
}

export function writeWorkspaceMemory(memory: WorkspaceMemory) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(memory))
    const params = new URLSearchParams(window.location.search)
    params.set('entity', memory.selectedId)
    params.set('view', memory.activeNav)
    params.set('stage', memory.activeStage)
    params.set('time', String(memory.timeline))
    params.set('zoom', String(memory.zoomLevel))
    memory.evidenceMode ? params.set('evidence', '1') : params.delete('evidence')
    memory.beforeAfter ? params.set('compare', '1') : params.delete('compare')
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
  } catch {
    // Persistence is an enhancement; the live workspace should remain usable if storage is blocked.
  }
}
