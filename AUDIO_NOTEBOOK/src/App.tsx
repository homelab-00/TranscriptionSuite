import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import CalendarView from './views/CalendarView';
import DayView from './views/DayView';
import SearchView from './views/SearchView';
import RecordingView from './views/RecordingView';
import ImportView from './views/ImportView';

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<CalendarView />} />
        <Route path="/day/:date" element={<DayView />} />
        <Route path="/search" element={<SearchView />} />
        <Route path="/recording/:id" element={<RecordingView />} />
        <Route path="/import" element={<ImportView />} />
      </Routes>
    </Layout>
  );
}

export default App;
