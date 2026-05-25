import React, { useState, useCallback } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import LoginPage from './LoginPage';
import MainLayout from './MainLayout';
import AdminPage from './AdminPage';
import { getToken } from './api';
import './styles.css';

function AppRoot() {
  const [loggedIn, setLoggedIn] = useState(() => !!getToken());

  const handleLogin = useCallback(() => setLoggedIn(true), []);
  const handleLogout = useCallback(() => setLoggedIn(false), []);

  return (
    <Routes>
      <Route
        path="/"
        element={
          loggedIn
            ? <MainLayout onLogout={handleLogout} />
            : <LoginPage onLogin={handleLogin} />
        }
      />
      <Route path="/admin" element={<AdminPage />} />
    </Routes>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppRoot />
    </BrowserRouter>
  </React.StrictMode>,
);
