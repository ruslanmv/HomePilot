/**
 * React glue for the TTS plugin registry.
 *
 * The app does NOT need to mount a provider: calling ``useActiveTts()``
 * reads from the registry directly and subscribes to its event bus for
 * re-renders. The dedicated ``<TtsEngineProvider>`` below is offered for
 * tests or for components that want the active engine in a React Context
 * rather than a subscription, but mounting it is optional.
 */
import React, { createContext, useCallback, useEffect, useMemo, useState } from 'react';
import { getActive, getActiveId, list, onActiveChange, setActive as registrySetActive, } from './registry';
const _Ctx = createContext(null);
export function TtsEngineProvider({ children }) {
    const [activeId, setActiveIdState] = useState(() => getActiveId());
    useEffect(() => {
        return onActiveChange(setActiveIdState);
    }, []);
    const setActive = useCallback((id) => {
        registrySetActive(id);
        setActiveIdState(id);
    }, []);
    const value = useMemo(() => ({
        activeId,
        active: getActive(),
        providers: list(),
        setActive,
    }), [activeId, setActive]);
    return <_Ctx.Provider value={value}>{children}</_Ctx.Provider>;
}
/** Convenience hook: works whether or not <TtsEngineProvider> is mounted.
 *  Falls back to a direct registry read + subscription so we do not force
 *  every feature to wrap its tree in a provider. */
export function useActiveTts() {
    const ctx = React.useContext(_Ctx);
    const [, tick] = useState(0);
    useEffect(() => {
        if (ctx)
            return;
        return onActiveChange(() => tick((t) => t + 1));
    }, [ctx]);
    if (ctx)
        return ctx;
    const activeId = getActiveId();
    return {
        activeId,
        active: getActive(),
        providers: list(),
        setActive: registrySetActive,
    };
}
