/* @aether/web/react v8.9.0 */
import { jsx } from 'react/jsx-runtime';
import { createContext, useState, useEffect, useContext } from 'react';

// The singleton is imported lazily so SSR bundles don't instantiate it.
// '@aether/web' is marked external so this import resolves correctly from dist/react.js.
let _instance = null;
const AetherContext = createContext(null);
function AetherProvider({ config, children }) {
    const [sdk, setSdk] = useState(null);
    useEffect(() => {
        if (typeof window === 'undefined')
            return;
        // Import via package name so the resolved path is dist/aether.esm.js, not dist/index.js.
        import('@aether/web').then(({ default: aether }) => {
            _instance = aether;
            aether.init(config);
            setSdk(aether);
        });
        return () => {
            _instance?.destroy?.();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    // Do not render children until the SDK is ready — hooks that call useAether() would throw
    // if rendered with a null context, producing a confusing error before the async import resolves.
    if (!sdk)
        return null;
    return (jsx(AetherContext.Provider, { value: { sdk }, children: children }));
}
function useAether() {
    const ctx = useContext(AetherContext);
    if (!ctx) {
        throw new Error('[Aether] useAether() must be used inside <AetherProvider>');
    }
    return ctx.sdk;
}
function useIdentity() {
    const sdk = useAether();
    const [identity, setIdentity] = useState(null);
    useEffect(() => {
        const current = sdk.getIdentity?.();
        if (current)
            setIdentity(current);
    }, [sdk]);
    return identity;
}
function useConsentState() {
    const sdk = useAether();
    const [state, setState] = useState(null);
    useEffect(() => {
        const current = sdk.consent?.getState?.();
        if (current)
            setState(current);
        const unsub = sdk.consent?.onUpdate?.(setState);
        return () => unsub?.();
    }, [sdk]);
    return state;
}
function useScreenOrPageTracking(name) {
    const sdk = useAether();
    useEffect(() => {
        if (!name)
            return;
        sdk.pageView?.(name);
    }, [sdk, name]);
}
function useJourneyResumed(cb) {
    const sdk = useAether();
    useEffect(() => {
        const unsub = sdk.onJourneyResumed?.(cb);
        return () => unsub?.();
    }, [sdk, cb]);
}

export { AetherProvider, useAether, useConsentState, useIdentity, useJourneyResumed, useScreenOrPageTracking };
//# sourceMappingURL=react.js.map
