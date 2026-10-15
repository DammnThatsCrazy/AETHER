import {
  confidenceIcons,
  freshnessIcons,
  provenanceIcons,
  resolveEntityIdentity,
  severityIcons,
  statusIcons,
  type CapabilityStatus,
  type Confidence,
  type EntityIdentity,
  type Freshness,
  type Provenance,
  type Severity,
} from '@olympus/brand';
import type { ComponentProps, HTMLAttributes } from 'react';

import { cn } from '../utils/cn';
import { Icon, type IconName } from './icon';

type IndicatorAttributes = Omit<HTMLAttributes<HTMLSpanElement>, 'children'>;

export interface EntityIconProps extends Omit<ComponentProps<typeof Icon>, 'decorative' | 'label' | 'name' | 'size'> {
  readonly entityType: EntityIdentity | string | null | undefined;
  readonly decorative?: boolean;
  readonly label?: string;
  readonly size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
}

/** Semantic base icon for an entity. Provider identity, if any, is a separate overlay. */
export function EntityIcon({ entityType, decorative = true, label, size = 'lg', className, ...props }: EntityIconProps) {
  const descriptor = resolveEntityIdentity(entityType);
  return (
    <Icon
      {...props}
      name={descriptor.icon}
      size={size}
      decorative={decorative}
      label={label ?? descriptor.label}
      className={className}
    />
  );
}

export interface EntityAvatarProps extends IndicatorAttributes {
  readonly entityType: EntityIdentity | string | null | undefined;
  readonly name?: string | null;
  readonly imageSrc?: string | null;
  readonly size?: number;
}

function initials(name: string | null | undefined): string | null {
  const words = name?.match(/[\p{L}\p{N}]+/gu) ?? [];
  const value = words.slice(0, 2).map(word => word[0] ?? '').join('').toUpperCase();
  return value || null;
}

/**
 * Entity identity treatment. A provided entity image is used as an avatar;
 * otherwise a name-derived initial is preferred before the typed entity icon.
 */
export function EntityAvatar({ entityType, name, imageSrc, size = 32, className, ...props }: EntityAvatarProps) {
  const descriptor = resolveEntityIdentity(entityType);
  const initialsValue = initials(name);
  const label = name ? `${name} (${descriptor.label})` : descriptor.label;
  const shapeClass = {
    circle: 'rounded-full',
    square: 'rounded-none',
    hexagon: 'rounded-[35%]',
    'rounded-square': 'rounded-md',
  }[descriptor.shape];

  return (
    <span
      {...props}
      className={cn('aether-entity-avatar inline-flex shrink-0 items-center justify-center overflow-hidden border border-border-subtle bg-surface-sunken text-text-secondary', shapeClass, className)}
      style={{ width: size, height: size, ...props.style }}
      role="img"
      aria-label={label}
    >
      {imageSrc ? <img src={imageSrc} alt="" aria-hidden="true" className="h-full w-full object-cover" />
        : initialsValue ? <span className="font-mono text-[0.62em] font-semibold leading-none">{initialsValue}</span>
          : <EntityIcon entityType={entityType} decorative size="md" />}
    </span>
  );
}

interface TextualIndicatorProps extends IndicatorAttributes {
  readonly showLabel?: boolean;
  readonly size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
}

function IndicatorLabel({ children, showLabel, className }: { readonly children: string; readonly showLabel: boolean; readonly className?: string }) {
  return showLabel ? <span className={cn('aether-semantic-indicator__label', className)}>{children}</span> : null;
}

export interface StatusIconProps extends TextualIndicatorProps {
  readonly status: CapabilityStatus;
}

/** Capability presentation that preserves the state text independently of color or shape. */
export function StatusIcon({ status, showLabel = true, size = 'sm', className, ...props }: StatusIconProps) {
  const descriptor = statusIcons[status];
  return (
    <span {...props} className={cn('aether-semantic-indicator inline-flex items-center gap-1.5', className)} data-tone={descriptor.tone}>
      <Icon name={descriptor.icon} size={size} decorative={showLabel} label={descriptor.label} />
      <IndicatorLabel showLabel={showLabel}>{descriptor.label}</IndicatorLabel>
    </span>
  );
}

export interface SeverityIconProps extends TextualIndicatorProps {
  readonly severity: Severity;
  readonly showPriority?: boolean;
}

/** Severity answers urgency only; its explicit label stays separate from lifecycle status. */
export function SeverityIcon({ severity, showLabel = true, showPriority = false, size = 'sm', className, ...props }: SeverityIconProps) {
  const descriptor = severityIcons[severity];
  const text = showPriority ? `${descriptor.label} (${descriptor.priority})` : descriptor.label;
  return (
    <span {...props} className={cn('aether-semantic-indicator inline-flex items-center gap-1.5', className)} data-severity={severity}>
      <Icon name={descriptor.icon} size={size} decorative={showLabel} label={descriptor.label} />
      <IndicatorLabel showLabel={showLabel}>{text}</IndicatorLabel>
    </span>
  );
}

export interface ProvenanceIconProps extends TextualIndicatorProps {
  readonly provenance: Provenance;
}

/** Provenance identifies where information came from, independently of freshness or confidence. */
export function ProvenanceIcon({ provenance, showLabel = true, size = 'sm', className, ...props }: ProvenanceIconProps) {
  const descriptor = provenanceIcons[provenance];
  return (
    <span {...props} className={cn('aether-semantic-indicator inline-flex items-center gap-1.5', className)} data-provenance={provenance}>
      <Icon name={descriptor.icon} size={size} decorative={showLabel} label={descriptor.label} />
      <IndicatorLabel showLabel={showLabel}>{descriptor.label}</IndicatorLabel>
    </span>
  );
}

export interface ConfidenceIndicatorProps extends TextualIndicatorProps {
  readonly confidence: Confidence;
}

/** Confidence states evidence certainty and intentionally does not imply severity or health. */
export function ConfidenceIndicator({ confidence, showLabel = true, size = 'sm', className, ...props }: ConfidenceIndicatorProps) {
  const descriptor = confidenceIcons[confidence];
  return (
    <span {...props} className={cn('aether-semantic-indicator inline-flex items-center gap-1.5', className)} data-confidence={confidence}>
      <Icon name={descriptor.icon} size={size} decorative={showLabel} label={descriptor.label} />
      <IndicatorLabel showLabel={showLabel}>{descriptor.label}</IndicatorLabel>
    </span>
  );
}

export interface FreshnessIconProps extends TextualIndicatorProps {
  readonly freshness: Freshness;
}

/** Freshness is a time signal; callers should show a timestamp when one is available. */
export function FreshnessIcon({ freshness, showLabel = true, size = 'sm', className, ...props }: FreshnessIconProps) {
  const descriptor = freshnessIcons[freshness];
  return (
    <span {...props} className={cn('aether-semantic-indicator inline-flex items-center gap-1.5', className)} data-freshness={freshness}>
      <Icon name={descriptor.icon} size={size} decorative={showLabel} label={descriptor.label} />
      <IndicatorLabel showLabel={showLabel}>{descriptor.label}</IndicatorLabel>
    </span>
  );
}

/** A semantic icon only, for dense entity/data visualizations that supply their own label. */
export function SemanticIcon({ name, label, decorative = true, size = 'sm', className }: {
  readonly name: IconName;
  readonly label?: string;
  readonly decorative?: boolean;
  readonly size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  readonly className?: string;
}) {
  return (
    <Icon
      name={name}
      decorative={decorative}
      size={size}
      className={className}
      {...(label === undefined ? {} : { label })}
    />
  );
}
