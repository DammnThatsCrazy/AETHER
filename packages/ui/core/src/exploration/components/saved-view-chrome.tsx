import { Button } from '../../components/button';
import { Select } from '../../components/select';

export interface SavedView {
  readonly id: string;
  readonly name: string;
}

export interface SavedViewChromeProps {
  readonly views: readonly SavedView[];
  readonly activeViewId?: string | null | undefined;
  /** From the surface capability — hides save controls honestly when false. */
  readonly supportsSavedViews?: boolean | undefined;
  readonly onSelect?: ((id: string) => void) | undefined;
  readonly onSave?: (() => void) | undefined;
  readonly onReset?: (() => void) | undefined;
}

/**
 * Saved-view chrome: pick a saved view, save the current exploration, or reset.
 * When the surface does not declare saved-view support, it says so instead of
 * offering controls that would silently do nothing.
 */
export function SavedViewChrome({
  views,
  activeViewId,
  supportsSavedViews = true,
  onSelect,
  onSave,
  onReset,
}: SavedViewChromeProps) {
  if (!supportsSavedViews) {
    return (
      <p className="text-xs text-text-muted" data-testid="saved-view-chrome">
        Saved views are not available on this surface.
      </p>
    );
  }
  return (
    <div className="flex items-center gap-2" data-testid="saved-view-chrome">
      {views.length > 0 && onSelect && (
        <Select
          label="Saved view"
          value={activeViewId ?? ''}
          onChange={onSelect}
          options={[
            { value: '', label: 'Current (unsaved)' },
            ...views.map((v) => ({ value: v.id, label: v.name })),
          ]}
        />
      )}
      {onSave && (
        <Button size="sm" variant="secondary" onClick={onSave}>
          Save view
        </Button>
      )}
      {onReset && (
        <Button size="sm" variant="ghost" onClick={onReset}>
          Reset
        </Button>
      )}
    </div>
  );
}
