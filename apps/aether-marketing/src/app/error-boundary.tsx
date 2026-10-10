import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  readonly children: ReactNode;
}

interface State {
  readonly hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Aether marketing render error', error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-surface-sunken px-6 text-center">
          <h1 className="text-2xl font-semibold text-text-primary">Something went wrong</h1>
          <p className="max-w-md text-sm text-text-secondary">
            An unexpected error interrupted this page. Reloading usually restores it.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-text-inverse mkt-motion-color hover:bg-accent-strong"
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
