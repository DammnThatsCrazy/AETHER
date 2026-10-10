import '@testing-library/jest-dom';

// jsdom does not implement matchMedia. Responsive brand helpers and shared
// components query it for reduced-motion / theme behavior, so supply a stub
// that reports "no preference" and never fires listeners.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// The shell resets scroll on route change; jsdom's scrollTo logs
// "Not implemented". Silence it with a no-op in the test realm.
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'scrollTo', {
    writable: true,
    configurable: true,
    value: () => {},
  });
}
