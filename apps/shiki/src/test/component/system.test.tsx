import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Badge } from '@shiki/components/system/badge';
import { Button } from '@shiki/components/system/button';
import { EmptyState } from '@shiki/components/system/empty-state';
import { ErrorState } from '@shiki/components/system/error-state';
import { LoadingState } from '@shiki/components/system/loading-state';
import { Skeleton } from '@shiki/components/system/skeleton';
import { StatusIndicator } from '@shiki/components/system/status-indicator';

describe('Badge', () => {
  it('renders children', () => {
    render(<Badge>Test</Badge>);
    expect(screen.getByText('Test')).toBeInTheDocument();
  });
  it('applies variant class', () => {
    render(<Badge variant="danger">Alert</Badge>);
    const badge = screen.getByText('Alert');
    expect(badge.className).toContain('danger');
  });
});

describe('Button', () => {
  it('renders with text', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });
  it('is disabled when prop set', () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByText('Disabled')).toBeDisabled();
  });
});

describe('EmptyState', () => {
  it('renders title and description', () => {
    render(<EmptyState title="No data" description="Nothing here yet" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
  });
});

describe('ErrorState', () => {
  it('renders error message', () => {
    render(<ErrorState message="Something broke" />);
    expect(screen.getByText('Something broke')).toBeInTheDocument();
  });
  it('shows retry button when onRetry provided', () => {
    render(<ErrorState message="Oops" onRetry={() => {}} />);
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });
});

describe('LoadingState', () => {
  it('renders skeleton lines', () => {
    const { container } = render(<LoadingState lines={4} />);
    const skeletons = container.querySelectorAll('[aria-hidden="true"]');
    expect(skeletons.length).toBe(4);
  });
});

describe('Skeleton', () => {
  it('renders as hidden element', () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });
});

describe('StatusIndicator', () => {
  it('renders with label', () => {
    render(<StatusIndicator status="healthy" label="OK" />);
    expect(screen.getByText('OK')).toBeInTheDocument();
  });
});
