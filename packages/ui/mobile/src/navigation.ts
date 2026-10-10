/**
 * Lightweight typed screen registry for the Aether mobile apps.
 *
 * Deliberately NOT a navigation library: a `RouteMap` (screen key → params) plus a
 * minimal stack machine. The React Native container that renders the current screen
 * lives in `./navigation-container.tsx`; this module is pure TypeScript (no react /
 * react-native import) so the registry is unit-testable in plain Node.
 *
 * The program keeps mobile dependencies light — no external navigation library
 * (e.g. @react-navigation) is used.
 */

/** Params carried by a screen route. */
export type RouteParams = Record<string, unknown>;

/** Screen key → params. `undefined` means the screen takes no params. */
export type RouteMap = Record<string, RouteParams | undefined>;

/** A concrete route on the stack. */
export interface RouteState<M extends RouteMap> {
  name: keyof M;
  params: M[keyof M];
}

/** Immutable snapshot of the navigator stack. */
export interface NavigatorState<M extends RouteMap> {
  stack: ReadonlyArray<RouteState<M>>;
}

/**
 * Pure navigator registry. `navigate`/`goBack`/`reset` mutate the stack and notify
 * subscribers; the React container (`./navigation-container.tsx`) subscribes to it,
 * and the host app calls the same methods from screens and deep-link handlers.
 */
export interface NavigatorRegistry<M extends RouteMap> {
  /** Push a screen onto the stack. Params flow through the route map type. */
  navigate<K extends keyof M>(name: K, params?: M[K]): void;
  /** Pop the top screen. No-op when only the root remains. */
  goBack(): void;
  /** Replace the whole stack with a single root (cold start / deep link). */
  reset<K extends keyof M>(name: K, params?: M[K]): void;
  /** The topmost route, or `null` when the stack is empty. */
  current(): RouteState<M> | null;
  /** Number of screens on the stack. */
  stackSize(): number;
  /** A defensive copy of the current stack state. */
  snapshot(): NavigatorState<M>;
  /** Subscribe to stack changes. Returns an unsubscribe function. */
  subscribe(listener: (state: NavigatorState<M>) => void): () => void;
}

export function createNavigatorRegistry<M extends RouteMap>(): NavigatorRegistry<M> {
  let stack: Array<RouteState<M>> = [];
  const listeners = new Set<(state: NavigatorState<M>) => void>();

  function emit(): void {
    const snapshot: NavigatorState<M> = { stack: stack.slice() };
    for (const listener of listeners) listener(snapshot);
  }

  /** Build a stack entry. The pair (name, params) is exactly one route in the map. */
  function makeRoute<K extends keyof M>(name: K, params: M[K] | undefined): RouteState<M> {
    // TS cannot reason about generic indexed-access assignability between `M[K]` and
    // `M[keyof M]` (a long-standing limitation), so we narrow once at this boundary
    // rather than scattering casts through every call site.
    return { name, params } as unknown as RouteState<M>;
  }

  return {
    navigate(name, params) {
      stack = [...stack, makeRoute(name, params)];
      emit();
    },
    goBack() {
      if (stack.length > 1) {
        stack = stack.slice(0, -1);
        emit();
      }
    },
    reset(name, params) {
      stack = [makeRoute(name, params)];
      emit();
    },
    current() {
      if (stack.length === 0) return null;
      const top = stack[stack.length - 1];
      return { name: top.name, params: top.params };
    },
    stackSize() {
      return stack.length;
    },
    snapshot() {
      return { stack: stack.slice() };
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
