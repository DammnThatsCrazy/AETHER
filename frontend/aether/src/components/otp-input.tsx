import { useRef, type KeyboardEvent, type ClipboardEvent } from 'react';
import { cn } from '@aether/ui';

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  error?: boolean;
  disabled?: boolean;
}

export function OtpInput({ value, onChange, length = 6, error = false, disabled = false }: OtpInputProps) {
  const inputRefs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = value.padEnd(length, '').split('').slice(0, length);

  function update(index: number, char: string) {
    const next = [...digits];
    next[index] = char;
    onChange(next.join('').replace(/[^0-9]/g, ''));
  }

  function handleKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace') {
      if (digits[index]) {
        update(index, '');
      } else if (index > 0) {
        update(index - 1, '');
        inputRefs.current[index - 1]?.focus();
      }
    } else if (e.key === 'ArrowLeft' && index > 0) {
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === 'ArrowRight' && index < length - 1) {
      inputRefs.current[index + 1]?.focus();
    }
  }

  function handleChange(index: number, raw: string) {
    const char = raw.replace(/[^0-9]/g, '').slice(-1);
    if (!char) return;
    update(index, char);
    if (index < length - 1) inputRefs.current[index + 1]?.focus();
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const chars = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, length).split('');
    const next = [...digits];
    chars.forEach((c, i) => { next[i] = c; });
    onChange(next.join('').trim());
    const focusIdx = Math.min(chars.length, length - 1);
    inputRefs.current[focusIdx]?.focus();
  }

  return (
    <div className="flex gap-2" role="group" aria-label="One-time password">
      {Array.from({ length }).map((_, i) => (
        <input
          key={i}
          ref={el => { inputRefs.current[i] = el; }}
          type="text"
          inputMode="numeric"
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          aria-label={`Digit ${i + 1} of ${length}`}
          maxLength={1}
          value={digits[i] ?? ''}
          disabled={disabled}
          onChange={e => handleChange(i, e.target.value)}
          onKeyDown={e => handleKeyDown(i, e)}
          onPaste={i === 0 ? handlePaste : undefined}
          className={cn(
            'w-10 h-12 text-center text-base font-mono border rounded bg-surface-raised text-text-primary focus:outline-none transition-colors',
            error
              ? 'border-danger ring-1 ring-danger/30'
              : digits[i]
                ? 'border-border-default'
                : 'border-border-default focus:border-accent focus:ring-1 focus:ring-accent/30',
            disabled && 'opacity-50 cursor-not-allowed',
          )}
        />
      ))}
    </div>
  );
}
