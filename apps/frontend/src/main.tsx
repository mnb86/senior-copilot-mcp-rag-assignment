import { Component, StrictMode } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

/** Shows start-up/render errors on screen instead of a blank page. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("GUI error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ padding: 24, fontFamily: "system-ui, sans-serif" }}>
        <h2>The copilot GUI hit an error</h2>
        <pre style={{ whiteSpace: "pre-wrap" }}>{String(this.state.error.stack ?? this.state.error)}</pre>
        <button type="button" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
