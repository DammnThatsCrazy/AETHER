// =============================================================================
// Aether SDK — MODULE PROXY UTILITY
// Creates a proxy that delegates method calls to an underlying module instance.
// Replaces verbose null-safe delegation boilerplate in SDK sub-interfaces.
// =============================================================================

/**
 * Creates a proxy that delegates all method calls to an underlying module instance.
 * Returns undefined/null for calls when module is not initialized.
 * Used to replace verbose null-safe delegation boilerplate in SDK sub-interfaces.
 */
export function createModuleProxy<T extends object>(
  getModule: () => T | null | undefined,
  defaults?: Record<string, unknown>
): T {
  return new Proxy({} as T, {
    get(_, prop: string) {
      return (...args: unknown[]) => {
        const mod = getModule();
        if (!mod) return defaults?.[prop] ?? undefined;
        const fn = (mod as Record<string, unknown>)[prop];
        return typeof fn === 'function' ? fn.apply(mod, args) : fn;
      };
    },
  });
}
