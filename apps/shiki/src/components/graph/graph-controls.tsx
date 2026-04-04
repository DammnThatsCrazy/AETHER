import { cn, formatTimestamp } from '@shiki/lib/utils';
import { Button, Select } from '@shiki/components/system';

// ---------------------------------------------------------------------------
// Speed options
// ---------------------------------------------------------------------------

const SPEED_OPTIONS = [
  { value: '0.5', label: '0.5x' },
  { value: '1', label: '1x' },
  { value: '2', label: '2x' },
  { value: '5', label: '5x' },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface GraphControlsProps {
  readonly isPlaying: boolean;
  readonly onPlay: () => void;
  readonly onPause: () => void;
  readonly onStop: () => void;
  readonly speed: string;
  readonly onSpeedChange: (speed: string) => void;
  readonly currentTime: number;
  readonly minTime: number;
  readonly maxTime: number;
  readonly onScrub: (time: number) => void;
  readonly currentTimestamp: string | null;
  readonly className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GraphControls({
  isPlaying,
  onPlay,
  onPause,
  onStop,
  speed,
  onSpeedChange,
  currentTime,
  minTime,
  maxTime,
  onScrub,
  currentTimestamp,
  className,
}: GraphControlsProps) {
  return (
    <div className={cn('flex items-center gap-3 p-3 bg-surface-raised border border-border-default rounded', className)}>
      {/* Play/Pause/Stop */}
      <div className="flex items-center gap-1">
        {isPlaying ? (
          <Button variant="secondary" size="sm" onClick={onPause}>
            Pause
          </Button>
        ) : (
          <Button variant="primary" size="sm" onClick={onPlay}>
            Play
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={onStop}>
          Stop
        </Button>
      </div>

      {/* Speed */}
      <Select
        options={SPEED_OPTIONS}
        value={speed}
        onChange={onSpeedChange}
      />

      {/* Scrub Slider */}
      <div className="flex-1 flex items-center gap-2">
        <input
          type="range"
          min={minTime}
          max={maxTime}
          value={currentTime}
          onChange={(e) => onScrub(Number(e.target.value))}
          className="flex-1 h-1.5 appearance-none bg-surface-default rounded-full cursor-pointer accent-accent"
        />
      </div>

      {/* Timestamp display */}
      {currentTimestamp && (
        <div className="text-xs font-mono text-text-secondary whitespace-nowrap">
          {formatTimestamp(currentTimestamp)}
        </div>
      )}
    </div>
  );
}
