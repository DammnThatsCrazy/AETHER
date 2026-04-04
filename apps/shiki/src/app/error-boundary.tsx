import { Component, type ReactNode, type ErrorInfo } from 'react';
import { ErrorState } from '@shiki/components/system';
import { log } from '@shiki/lib/logging';

interface Props {
  readonly children: ReactNode;
  readonly fallback?: ReactNode;
  readonly onError?: (error: Error, info: ErrorInfo) => void;
}

interface State {
  readonly hasError: boolean;
  readonly error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    log.error('[ErrorBoundary] Caught error', { error: error.message, stack: error.stack, componentStack: info.componentStack });
    this.props.onError?.(error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <ErrorState
          title="Something went wrong"
          message={this.state.error?.message ?? 'An unexpected error occurred'}
          onRetry={() => this.setState({ hasError: false, error: null })}
        />
      );
    }
    return this.props.children;
  }
}
