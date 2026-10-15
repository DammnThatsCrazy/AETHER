import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  readonly children: ReactNode;
}

interface State {
  readonly hasError: boolean;
}

/** Recovers the shell around a failed workspace instead of blanking the page. */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[olympus-marketing] page error:', error, info);
  }

  override render(): ReactNode {
    if (this.state.hasError) {
      return (
        <section className="mkt-container flex min-h-[60vh] flex-col items-start justify-center py-24">
          <p className="mkt-eyebrow">Something went wrong</p>
          <h1 className="mkt-display mt-4">This page could not be rendered.</h1>
          <p className="mkt-lead mt-4 max-w-xl">
            The error is isolated to this workspace. Reload to continue, or return to the home page.
          </p>
          <button
            type="button"
            className="mt-8 rounded-md bg-accent px-4 py-2 font-medium text-text-inverse"
            onClick={() => {
              this.setState({ hasError: false });
              window.location.reload();
            }}
          >
            Reload
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
