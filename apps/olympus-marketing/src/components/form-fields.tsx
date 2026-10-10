import { cn } from '@aether/ui';

/**
 * Shared presentational field primitives for the Olympus Labs marketing forms
 * (waitlist, demo request). Kept local to this workspace — a labeled control
 * with honest inline validation wired via aria-invalid + aria-describedby, so
 * a failure is programmatically discoverable rather than color-only.
 */

const fieldClass = (hasError: boolean) =>
  cn(
    'mt-2 w-full rounded-md border bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1',
    hasError ? 'border-danger focus:ring-danger' : 'border-border-default focus:ring-border-focus',
  );

interface FieldShellProps {
  readonly id: string;
  readonly label: string;
  readonly error?: string | undefined;
  readonly optional?: boolean | undefined;
}

function FieldLabel({ id, label, optional }: Pick<FieldShellProps, 'id' | 'label' | 'optional'>) {
  return (
    <label htmlFor={id} className="block text-sm font-medium text-text-primary">
      {label}
      {optional === true && <span className="ml-1 font-normal text-text-muted">(optional)</span>}
    </label>
  );
}

function FieldError({ id, error }: { readonly id: string; readonly error: string | undefined }) {
  if (error === undefined) return null;
  return (
    <p id={id} role="alert" className="mt-1.5 text-sm text-danger">
      {error}
    </p>
  );
}

interface TextFieldProps extends FieldShellProps {
  readonly type?: 'text' | 'email';
  readonly autoComplete?: string;
  readonly required?: boolean;
  readonly value: string;
  readonly onValueChange: (value: string) => void;
}

export function TextField({
  id,
  label,
  type = 'text',
  autoComplete,
  required = false,
  optional,
  value,
  onValueChange,
  error,
}: TextFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div>
      <FieldLabel id={id} label={label} optional={optional} />
      <input
        id={id}
        name={id}
        type={type}
        autoComplete={autoComplete}
        required={required}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        aria-invalid={error !== undefined}
        {...(error !== undefined ? { 'aria-describedby': errorId } : {})}
        className={fieldClass(error !== undefined)}
      />
      <FieldError id={errorId} error={error} />
    </div>
  );
}

interface SelectFieldProps extends FieldShellProps {
  readonly required?: boolean;
  readonly value: string;
  readonly onValueChange: (value: string) => void;
  readonly options: readonly { readonly value: string; readonly label: string }[];
  readonly placeholder: string;
}

export function SelectField({
  id,
  label,
  required = false,
  optional,
  value,
  onValueChange,
  options,
  placeholder,
  error,
}: SelectFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div>
      <FieldLabel id={id} label={label} optional={optional} />
      <select
        id={id}
        name={id}
        required={required}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        aria-invalid={error !== undefined}
        {...(error !== undefined ? { 'aria-describedby': errorId } : {})}
        className={fieldClass(error !== undefined)}
      >
        <option value="" disabled>
          {placeholder}
        </option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <FieldError id={errorId} error={error} />
    </div>
  );
}

interface TextareaFieldProps extends FieldShellProps {
  readonly required?: boolean;
  readonly value: string;
  readonly onValueChange: (value: string) => void;
  readonly rows?: number;
  readonly placeholder?: string;
}

export function TextareaField({
  id,
  label,
  required = false,
  optional,
  value,
  onValueChange,
  rows = 4,
  placeholder,
  error,
}: TextareaFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div>
      <FieldLabel id={id} label={label} optional={optional} />
      <textarea
        id={id}
        name={id}
        required={required}
        rows={rows}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        aria-invalid={error !== undefined}
        {...(error !== undefined ? { 'aria-describedby': errorId } : {})}
        className={fieldClass(error !== undefined)}
      />
      <FieldError id={errorId} error={error} />
    </div>
  );
}
