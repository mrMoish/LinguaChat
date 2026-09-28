import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'

// Enhanced console logging for debugging
let isLoggingError = false;
const originalConsoleError = console.error;
console.error = function(...args) {
  // Prevent recursive calls
  if (isLoggingError) {
    return;
  }
  isLoggingError = true;

  try {
    originalConsoleError('\n=== CONSOLE ERROR ===');
    originalConsoleError('Timestamp:', new Date().toISOString());
    originalConsoleError('Arguments:', ...args);
    originalConsoleError('Call Stack:', new Error().stack);
    originalConsoleError('==================\n');

    // Send error to dev server for terminal output
    try {
      fetch('/__client-error', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          timestamp: new Date().toISOString(),
          args: args.map(a => String(a)),
          stack: new Error().stack,
          userAgent: navigator.userAgent,
          url: window.location.href,
        }),
      }).catch(() => {});
    } catch (e) {
      // Ignore fetch errors
    }
  } finally {
    isLoggingError = false;
  }
};

// Diagnostic loading indicator
const rootElement = document.getElementById('root');
if (rootElement) {
  rootElement.innerHTML = '<div style="padding:40px;text-align:center;font-family:sans-serif;color:#666;">Загрузка...</div>';
}

// Force Service Worker update and clear caches on iOS
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.getRegistrations().then(registrations => {
      registrations.forEach(registration => {
        registration.unregister();
      });
    });
    if (caches) {
      caches.keys().then(names => {
        names.forEach(name => caches.delete(name));
      });
    }
  });
}

// Error boundary with detailed error display for debugging on iOS
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('React Error:', error, errorInfo);

    // Get recent call log if available
    let recentCalls = 'Call log not available';
    if (window.__getCallLog) {
      try {
        const callLog = window.__getCallLog();
        recentCalls = callLog.slice(-20).map(entry =>
          entry.time + ' | ' + entry.name + ' | ' + entry.args
        ).join('\n');
      } catch (e) {
        recentCalls = 'Failed to get call log: ' + e.message;
      }
    }

    const errorDetails = [
      '=== REACT ERROR ===',
      '',
      'Message: ' + (error?.message || error),
      '',
      'Component Stack: ' + (errorInfo?.componentStack || 'N/A'),
      '',
      'Error Stack: ' + (error?.stack || 'N/A'),
      '',
      '=== RECENT CALLS ===',
      recentCalls,
      '',
      '=== USER AGENT ===',
      navigator.userAgent,
      '',
      '=== LOCATION ===',
      window.location.href,
      '',
      '=== SCREEN ===',
      window.innerWidth + 'x' + window.innerHeight,
      '',
      '=== TIMESTAMP ===',
      new Date().toISOString(),
    ].join('\n');

    document.body.innerHTML = '<div style="padding:16px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:13px;color:#333;background:#fff;min-height:100vh;word-break:break-word;">' +
      '<h2 style="color:#d32f2f;margin:0 0 12px;font-size:18px;">React Error</h2>' +
      '<h3 style="color:#1976d2;margin:0 0 8px;font-size:14px;">Error Details:</h3>' +
      '<pre style="white-space:pre-wrap;background:#f5f5f5;padding:12px;border-radius:8px;font-size:11px;max-height:25vh;overflow-y:auto;margin:0 0 12px;border-left:4px solid #d32f2f;">' + errorDetails + '</pre>' +
      '<h3 style="color:#1976d2;margin:0 0 8px;font-size:14px;">Recent Calls:</h3>' +
      '<pre style="white-space:pre-wrap;background:#e3f2fd;padding:12px;border-radius:8px;font-size:11px;max-height:25vh;overflow-y:auto;margin:0 0 12px;border-left:4px solid #1976d2;">' + recentCalls + '</pre>' +
      '<button onclick="location.reload()" style="padding:10px 20px;font-size:14px;background:#1976d2;color:#fff;border:none;border-radius:4px;cursor:pointer;margin-right:8px;">Обновить страницу</button>' +
      '<button onclick="navigator.clipboard.writeText(document.querySelectorAll(\'pre\')[0].textContent);this.textContent=\'Скопировано!\'" style="padding:10px 20px;font-size:14px;background:#757575;color:#fff;border:none;border-radius:4px;cursor:pointer;">Скопировать ошибку</button>' +
      '</div>';
  }

  render() {
    if (this.state.hasError) {
      return null;
    }
    return this.props.children;
  }
}

// Disable StrictMode to prevent double rendering issues on iOS
ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
)