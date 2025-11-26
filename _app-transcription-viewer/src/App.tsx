import { Routes, Route } from 'react-router-dom';
import { Box } from '@mui/material';
import Layout from './components/Layout';
import CalendarView from './views/CalendarView';
import SearchView from './views/SearchView';
import RecordingView from './views/RecordingView';
import ImportView from './views/ImportView';

function App() {
  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <Layout>
        <Routes>
          <Route path="/" element={<CalendarView />} />
          <Route path="/search" element={<SearchView />} />
          <Route path="/recording/:id" element={<RecordingView />} />
          <Route path="/import" element={<ImportView />} />
        </Routes>
      </Layout>
    </Box>
  );
}

export default App;
