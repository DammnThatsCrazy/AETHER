import { createContext, useContext, useState, type ReactNode } from 'react';
import { cn } from '@shiki/lib/utils';

interface TabsContextValue {
  readonly activeTab: string;
  readonly setActiveTab: (tab: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

interface TabsProps {
  readonly defaultValue?: string | undefined;
  readonly value?: string | undefined;
  readonly children: ReactNode;
  readonly className?: string | undefined;
  readonly onChange?: ((value: string) => void) | undefined;
  readonly onValueChange?: ((value: string) => void) | undefined;
}

export function Tabs({ defaultValue, value, children, className, onChange, onValueChange }: TabsProps) {
  const [activeTab, setActiveTabState] = useState(value ?? defaultValue ?? '');
  const setActiveTab = (tab: string) => {
    setActiveTabState(tab);
    onChange?.(tab);
    onValueChange?.(tab);
  };
  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab }}>
      <div className={cn('w-full', className)}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ children, className }: { readonly children: ReactNode; readonly className?: string | undefined }) {
  return (
    <div className={cn('flex border-b border-border-default gap-1 mb-4', className)} role="tablist">
      {children}
    </div>
  );
}

export function TabsTrigger({ value, children, className }: { readonly value: string; readonly children: ReactNode; readonly className?: string | undefined }) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error('TabsTrigger must be inside Tabs');
  const isActive = ctx.activeTab === value;
  return (
    <button
      role="tab"
      aria-selected={isActive}
      onClick={() => ctx.setActiveTab(value)}
      className={cn(
        'px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px',
        isActive ? 'border-accent text-accent' : 'border-transparent text-text-secondary hover:text-text-primary',
        className,
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, children, className }: { readonly value: string; readonly children: ReactNode; readonly className?: string | undefined }) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error('TabsContent must be inside Tabs');
  if (ctx.activeTab !== value) return null;
  return <div className={cn('', className)} role="tabpanel">{children}</div>;
}
