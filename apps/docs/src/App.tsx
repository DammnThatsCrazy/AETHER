import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import DocIndex from './pages/DocIndex';
import DocViewer from './pages/DocViewer';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DocIndex tier="P" />} />
        <Route path="/doc/:slug" element={<DocViewer />} />
        {/* Redirect unknown paths to index */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
