import { useState, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Entity, EntityType } from '@shiki/types';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  Button,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  TerminalSeparator,
} from '@shiki/components/system';
import { PageWrapper } from '@shiki/components/layout';
import { EntityListTable } from '@shiki/components/entities';
import { getMockEntities } from '@shiki/fixtures/entities';
import { Entity360Page } from './entity-360';

const ENTITY_TYPES: EntityType[] = [
  'customer',
  'wallet',
  'agent',
  'protocol',
  'contract',
  'cluster',
];

const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  customer: 'Customers',
  wallet: 'Wallets',
  agent: 'Agents',
  protocol: 'Protocols',
  contract: 'Contracts',
  cluster: 'Clusters',
};

export function EntitiesPage() {
  const { type: routeType, id: routeId } = useParams<{ type?: string; id?: string }>();
  const navigate = useNavigate();

  const [activeType, setActiveType] = useState<EntityType>(
    (ENTITY_TYPES.includes(routeType as EntityType) ? routeType : 'customer') as EntityType,
  );
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(routeId ?? null);

  const entities = useMemo(() => getMockEntities(activeType), [activeType]);

  const handleSelectEntity = useCallback(
    (entity: Entity) => {
      setSelectedEntityId(entity.id);
      navigate(`/entities/${entity.type}/${entity.id}`, { replace: true });
    },
    [navigate],
  );

  const handleBack = useCallback(() => {
    setSelectedEntityId(null);
    navigate(`/entities/${activeType}`, { replace: true });
  }, [navigate, activeType]);

  const handleTypeChange = useCallback(
    (type: string) => {
      const entityType = type as EntityType;
      setActiveType(entityType);
      setSelectedEntityId(null);
      navigate(`/entities/${entityType}`, { replace: true });
    },
    [navigate],
  );

  // If we have a selected entity (via route param or click), show the 360 view
  if (selectedEntityId) {
    return (
      <PageWrapper title="Entity 360">
        <Entity360Page entityId={selectedEntityId} onBack={handleBack} />
      </PageWrapper>
    );
  }

  // Entity type counts for the tabs
  const typeCounts = useMemo(() => {
    const counts: Partial<Record<EntityType, number>> = {};
    for (const t of ENTITY_TYPES) {
      counts[t] = getMockEntities(t).length;
    }
    return counts;
  }, []);

  return (
    <PageWrapper title="Entities">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-bold text-neutral-100">Entities</h1>
          <span className="text-xs text-neutral-500 font-mono">
            {entities.length} {ENTITY_TYPE_LABELS[activeType].toLowerCase()}
          </span>
        </div>

        <TerminalSeparator />

        {/* Entity Type Selector */}
        <Tabs defaultValue={activeType} onValueChange={handleTypeChange}>
          <TabsList>
            {ENTITY_TYPES.map((type) => (
              <TabsTrigger key={type} value={type}>
                {ENTITY_TYPE_LABELS[type]}
                <Badge variant="default" className="ml-1.5 text-xs">
                  {typeCounts[type] ?? 0}
                </Badge>
              </TabsTrigger>
            ))}
          </TabsList>

          {ENTITY_TYPES.map((type) => (
            <TabsContent key={type} value={type}>
              <Card>
                <CardHeader>
                  <CardTitle>{ENTITY_TYPE_LABELS[type]}</CardTitle>
                </CardHeader>
                <CardContent>
                  <EntityListTable
                    entities={type === activeType ? entities : getMockEntities(type)}
                    onSelect={handleSelectEntity}
                  />
                </CardContent>
              </Card>
            </TabsContent>
          ))}
        </Tabs>
      </div>
    </PageWrapper>
  );
}
