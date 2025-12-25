import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import CalendarView from './views/CalendarView';
import DayView from './views/DayView';
import SearchView from './views/SearchView';
import RecordingView from './views/RecordingView';
import ImportView from './views/ImportView';
import RecordView from './views/RecordView';
import AdminView from './views/AdminView';

// Detect which section we're in based on URL
const getCurrentSection = (): 'notebook' | 'record' | 'admin' => {
  const path = window.location.pathname;
  if (path.startsWith('/record')) return 'record';
  if (path.startsWith('/admin')) return 'admin';
  return 'notebook';
};

function App() {
  const section = getCurrentSection();

  return (
    <Layout>
      <Routes>
        {section === 'notebook' && (
          <>
            <Route path="/calendar" element={<CalendarView />} />
            <Route path="/day/:date" element={<DayView />} />
            <Route path="/search" element={<SearchView />} />
            <Route path="/recording/:id" element={<RecordingView />} />
            <Route path="/import" element={<ImportView />} />
            <Route path="/" element={<CalendarView />} />
          </>
        )}
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
