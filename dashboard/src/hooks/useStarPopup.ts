import { useState, useEffect, useRef } from 'react';
import { getConfig, setConfig } from '../config/store';

const TWO_HOURS_MS = 2 * 60 * 60 * 1000;
const TICK_INTERVAL_MS = 60_000; // 1 minute

export function useStarPopup() {
  const [showStarPopup, setShowStarPopup] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      const alreadyShown = (await getConfig<boolean>('app.starPopupShown')) ?? false;
      if (alreadyShown || cancelled) return;

      let cumulativeMs = (await getConfig<number>('app.cumulativeUsageMs')) ?? 0;

      // Check immediately in case already past threshold
      if (cumulativeMs >= TWO_HOURS_MS) {
        if (!cancelled) {
          setShowStarPopup(true);
          await setConfig('app.starPopupShown', true);
        }
        return;
      }

      intervalRef.current = setInterval(async () => {
        cumulativeMs += TICK_INTERVAL_MS;
        await setConfig('app.cumulativeUsageMs', cumulativeMs);

        if (cumulativeMs >= TWO_HOURS_MS) {
          setShowStarPopup(true);
          await setConfig('app.starPopupShown', true);
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
        }
      }, TICK_INTERVAL_MS);
    }

    void init();

    return () => {
      cancelled = true;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, []);

  const dismissStarPopup = async () => {
    setShowStarPopup(false);
    await setConfig('app.starPopupShown', true);
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  return { showStarPopup, dismissStarPopup };
}
