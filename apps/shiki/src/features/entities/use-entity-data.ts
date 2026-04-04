import { useState, useEffect } from 'react';
import type { Entity, EntityType } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockEntities, getMockEntity } from '@shiki/fixtures/entities';

export function useEntityData(type?: EntityType, id?: string) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (isLocalMocked()) {
      setEntities(getMockEntities(type));
      if (id) {
        setSelectedEntity(getMockEntity(id) ?? null);
      }
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    const params = type ? `?type=${type}` : '';
    fetch(`/api/v1/intelligence/entities${params}`)
      .then(r => r.json())
      .then(() => {
        setEntities(getMockEntities(type));
        if (id) setSelectedEntity(getMockEntity(id) ?? null);
        setIsLoading(false);
      })
      .catch(() => {
        setEntities([]);
        setIsLoading(false);
      });
  }, [type, id]);

  return { entities, selectedEntity, setSelectedEntity, isLoading };
}
