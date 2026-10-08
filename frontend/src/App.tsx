import { BrowserRouter, Routes, Route } from 'react-router-dom';
import AppShell from './components/layout/AppShell';
import HomePage from './pages/v2/HomePage';
import CourseWorkspace from './pages/v2/CourseWorkspace';
import JobsPage from './pages/v2/JobsPage';
import AcademicsPage from './pages/v2/AcademicsPage';
import Dashboard from './pages/Dashboard';
import PapersPage from './pages/PapersPage';
import QuestionsPage from './pages/QuestionsPage';
import SyllabusPage from './pages/SyllabusPage';
import AnalysisPage from './pages/AnalysisPage';
import PredictionsPage from './pages/PredictionsPage';
import AttemptsPage from './pages/AttemptsPage';
import MasteryPage from './pages/MasteryPage';
import ReviewQueuePage from './pages/ReviewQueuePage';
import SettingsPage from './pages/SettingsPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="courses" element={<HomePage />} />
          <Route path="courses/:code" element={<CourseWorkspace />} />
          <Route path="courses/:code/:tab" element={<CourseWorkspace />} />
          <Route path="academics" element={<AcademicsPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          {/* Classic (v1) pages, kept until Phase 2 replaces them */}
          <Route path="classic" element={<Dashboard />} />
          <Route path="papers" element={<PapersPage />} />
          <Route path="questions" element={<QuestionsPage />} />
          <Route path="syllabus" element={<SyllabusPage />} />
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="predictions" element={<PredictionsPage />} />
          <Route path="attempts" element={<AttemptsPage />} />
          <Route path="mastery" element={<MasteryPage />} />
          <Route path="review" element={<ReviewQueuePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
