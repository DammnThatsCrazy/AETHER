/** Full-page navigation to another origin (a seam tests can replace). */
export function leaveFor(href: string): void {
  window.location.replace(href);
}
