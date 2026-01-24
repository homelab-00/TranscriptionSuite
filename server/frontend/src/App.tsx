import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import RecordView from './views/RecordView';
import AdminView from './views/AdminView';

// Detect which section we're in based on URL
const getCurrentSection = (): 'record' | 'admin' => {
  const path = window.location.pathname;
  if (path.startsWith('/admin')) return 'admin';
  return 'record';
};

function App() {
  const section = getCurrentSection();

  return (
    <Layout>
      <Routes>
        {section === 'record' && (
          <Route path="/" element={<RecordView />} />
        )}
        {section === 'admin' && (
          <Route path="/" element={<AdminView />} />
        )}
      </Routes>
    </Layout>
  );
}

export default App;
