import type { ReactNode } from 'react';
import Sidebar from './Sidebar';

interface Props {
  children: ReactNode;
}

export default function Layout({ children }: Props) {
  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      <Sidebar />
      <main style={{ flex: 1, minWidth: 0, overflowY: 'auto' }}>
        {children}
      </main>
    </div>
  );
}
