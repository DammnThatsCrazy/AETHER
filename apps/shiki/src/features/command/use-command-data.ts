import { useState, useEffect } from 'react';
import type { Controller, ControllerObjective, ControllerSchedule, CHARStatus, ControllerDisplayMode } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockControllers, MOCK_OBJECTIVES, MOCK_SCHEDULES, MOCK_CHAR_STATUS } from '@shiki/fixtures/controllers';

export function useCommandData() {
  const [controllers, setControllers] = useState<Controller[]>([]);
  const [objectives, setObjectives] = useState<ControllerObjective[]>([]);
  const [schedules, setSchedules] = useState<ControllerSchedule[]>([]);
  const [charStatus, setCharStatus] = useState<CHARStatus | null>(null);
  const [displayMode, setDisplayMode] = useState<ControllerDisplayMode>('functional');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (isLocalMocked()) {
      setControllers(getMockControllers());
      setObjectives(MOCK_OBJECTIVES);
      setSchedules(MOCK_SCHEDULES);
      setCharStatus(MOCK_CHAR_STATUS);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    fetch('/api/v1/agent/controllers')
      .then(r => r.json())
      .then(() => {
        setControllers(getMockControllers());
        setObjectives(MOCK_OBJECTIVES);
        setSchedules(MOCK_SCHEDULES);
        setCharStatus(MOCK_CHAR_STATUS);
        setIsLoading(false);
      })
      .catch(() => {
        setControllers([]);
        setIsLoading(false);
      });
  }, []);

  return { controllers, objectives, schedules, charStatus, displayMode, setDisplayMode, isLoading };
}
