import type { LiveEvent } from '@shiki/types';

export interface ReplaySession {
  readonly id: string;
  readonly events: readonly LiveEvent[];
  readonly startTime: string;
  readonly endTime: string;
  readonly speed: number;
}

export interface ReplayState {
  readonly isPlaying: boolean;
  readonly currentIndex: number;
  readonly speed: number;
  readonly session: ReplaySession | null;
}

export function createReplayController(
  events: readonly LiveEvent[],
  onEvent: (event: LiveEvent) => void,
) {
  let currentIndex = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let speed = 1;
  let isPlaying = false;

  function play(): void {
    if (isPlaying || currentIndex >= events.length) return;
    isPlaying = true;
    scheduleNext();
  }

  function pause(): void {
    isPlaying = false;
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function stop(): void {
    pause();
    currentIndex = 0;
  }

  function seek(index: number): void {
    currentIndex = Math.max(0, Math.min(index, events.length - 1));
  }

  function setSpeed(s: number): void {
    speed = s;
  }

  function scheduleNext(): void {
    if (!isPlaying || currentIndex >= events.length) {
      isPlaying = false;
      return;
    }

    const event = events[currentIndex];
    if (!event) return;
    onEvent(event);
    currentIndex++;

    if (currentIndex < events.length) {
      const nextEvent = events[currentIndex];
      if (nextEvent) {
        const delay = Math.max(
          50,
          (new Date(nextEvent.timestamp).getTime() - new Date(event.timestamp).getTime()) / speed,
        );
        timer = setTimeout(scheduleNext, delay);
      }
    } else {
      isPlaying = false;
    }
  }

  return { play, pause, stop, seek, setSpeed, getState: () => ({ isPlaying, currentIndex, speed }) };
}
