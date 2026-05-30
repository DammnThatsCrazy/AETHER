import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import DocIndex from './pages/DocIndex';
import DocViewer from './pages/DocViewer';
import ArtifactsIndex from './pages/artifacts/ArtifactsIndex';
import EventRegistry from './pages/artifacts/EventRegistry';
import EnvVars from './pages/artifacts/EnvVars';
import PlansTable from './pages/artifacts/PlansTable';
import Providers from './pages/artifacts/Providers';
import { getBundleTier } from './lib/tier';

const tier = getBundleTier();

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DocIndex tier={tier} />} />
          <Route path="/doc/:slug" element={<DocViewer />} />
          <Route path="/artifacts" element={<ArtifactsIndex />} />
          <Route path="/artifacts/events" element={<EventRegistry />} />
          <Route path="/artifacts/env" element={<EnvVars />} />
          <Route path="/artifacts/plans" element={<PlansTable />} />
          <Route path="/artifacts/providers" element={<Providers />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
