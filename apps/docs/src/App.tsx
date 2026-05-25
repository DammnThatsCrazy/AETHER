import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import DocIndex from './pages/DocIndex';
import DocViewer from './pages/DocViewer';
import { getBundleTier } from './lib/tier';

const tier = getBundleTier();

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DocIndex tier={tier} />} />
          <Route path="/doc/:slug" element={<DocViewer />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
