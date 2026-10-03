/** Visible on focus; jumps past the header to the page's `#main` landmark. */
export function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-control focus:bg-ink focus:px-3.5 focus:py-2 focus:text-body-sm focus:font-medium focus:text-stone-50"
    >
      Skip to content
    </a>
  );
}
