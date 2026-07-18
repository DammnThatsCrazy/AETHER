import { useState } from 'react';
import type { ExplorationSurfaceId } from '@aether/shared/surface-capabilities';
import type { FilterExpression, FilterOperator } from '@aether/shared/graph-contract';
import { Button } from '../../components/button';
import { Select } from '../../components/select';
import { Input } from '../../components/input';
import {
  filterFieldsForSurface,
  operatorsForField,
  isValuelessOperator,
  isRangeOperator,
  isMultiValueOperator,
} from '../registry';
import { buildFilterExpression, operatorLabel } from '../filter-model';

export interface FilterBuilderProps {
  /** Surface whose registered field categories bound the field picker. */
  readonly surface: ExplorationSurfaceId;
  /** Receives a registry-valid FilterExpression when the user adds one. */
  readonly onAdd: (expr: FilterExpression) => void;
}

function valuePlaceholder(op: FilterOperator): string {
  if (isMultiValueOperator(op)) return 'comma,separated,values';
  if (isRangeOperator(op)) return 'from..to';
  return 'value';
}

/**
 * Registry-driven filter builder: field picker (constrained to the surface's
 * registered field categories) → operator picker (constrained to that field's
 * registered operators) → typed value input. Never offers a field/operator the
 * contract does not define, so it can only ever build a valid FilterExpression.
 */
export function FilterBuilder({ surface, onAdd }: FilterBuilderProps) {
  const fields = filterFieldsForSurface(surface);
  const [field, setField] = useState<string>(() => fields[0]?.id ?? '');
  const operators = field ? operatorsForField(field) : [];
  const [op, setOp] = useState<FilterOperator>(() => operators[0] ?? 'eq');
  const [raw, setRaw] = useState('');

  if (fields.length === 0) {
    return <p className="text-xs text-text-muted">No filterable fields for this surface.</p>;
  }

  const onFieldChange = (next: string) => {
    setField(next);
    const nextOps = operatorsForField(next);
    setOp(nextOps[0] ?? 'eq');
    setRaw('');
  };

  const needsValue = !isValuelessOperator(op);
  const candidate = field ? buildFilterExpression(field, op, raw) : null;

  const submit = () => {
    if (candidate) {
      onAdd(candidate);
      setRaw('');
    }
  };

  return (
    <div className="flex flex-wrap items-end gap-2">
      <Select
        label="Field"
        value={field}
        onChange={onFieldChange}
        options={fields.map((f) => ({ value: f.id, label: f.label }))}
      />
      <Select
        label="Operator"
        value={op}
        onChange={(v) => setOp(v as FilterOperator)}
        options={operators.map((o) => ({ value: o, label: operatorLabel(o) }))}
      />
      {needsValue && (
        <Input
          label="Value"
          value={raw}
          placeholder={valuePlaceholder(op)}
          onChange={(e) => setRaw(e.target.value)}
        />
      )}
      <Button size="sm" variant="secondary" onClick={submit} disabled={!candidate}>
        Add filter
      </Button>
    </div>
  );
}
