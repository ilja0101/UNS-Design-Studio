import { Component, type ErrorInfo, type ReactNode } from "react";

// A render error anywhere below used to unmount the whole React tree, leaving a
// blank white page. This boundary catches it and shows a recoverable card
// instead — the app never goes fully white. `resetKey` lets a parent clear the
// error when the user navigates (so a crash on one page doesn't wedge the rest).
interface Props {
  children: ReactNode;
  resetKey?: unknown;
  label?: string;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error boundary caught:", error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full w-full items-center justify-center p-8">
          <div className="max-w-md rounded-xl border border-border bg-surface p-6 text-center shadow-card">
            <p className="text-sm font-semibold text-fg">
              {this.props.label ?? "Something went wrong in this view"}
            </p>
            <p className="mt-1 break-words text-xs text-fg-muted">{this.state.error.message}</p>
            <div className="mt-4 flex justify-center gap-2">
              <button
                onClick={() => this.setState({ error: null })}
                className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover"
              >
                Try again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="rounded-lg border border-border bg-surface px-3.5 py-2 text-sm font-medium text-fg hover:bg-surface-2"
              >
                Reload page
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
