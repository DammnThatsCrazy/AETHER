/**
 * Creates a proxy that delegates all method calls to an underlying module instance.
 * Returns undefined/null for calls when module is not initialized.
 * Used to replace verbose null-safe delegation boilerplate in SDK sub-interfaces.
 */
export declare function createModuleProxy<T extends object>(getModule: () => T | null | undefined, defaults?: Record<string, unknown>): T;
