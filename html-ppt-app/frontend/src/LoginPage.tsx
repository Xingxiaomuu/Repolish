import { useState } from 'react';
import { authLogin, authRegister } from './api';

interface Props {
  onLogin: () => void;
}

export default function LoginPage({ onLogin }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const switchMode = () => {
    setMode(mode === 'login' ? 'register' : 'login');
    setError('');
    setSuccess('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      if (mode === 'register') {
        if (password !== confirmPassword) {
          setError('Passwords do not match.');
          setLoading(false);
          return;
        }
        await authRegister(name, email, password);
        setSuccess('Registration successful! Please login.');
        setMode('login');
        setPassword('');
        setConfirmPassword('');
      } else {
        await authLogin(email, password);
        onLogin();
      }
    } catch (err: any) {
      setError(err.message || 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <h1>开始你的 HTML 之旅</h1>
          <p>将长文本报告转化为专业阅读型 HTML PPT。</p>
        </div>

        {success && <div className="auth-msg success">{success}</div>}
        {error && <div className="auth-msg error">{error}</div>}

        <form onSubmit={handleSubmit} className="auth-form">
          {mode === 'register' && (
            <div className="field">
              <label htmlFor="reg-name">Name</label>
              <input
                id="reg-name"
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Your name"
                required
              />
            </div>
          )}

          <div className="field">
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>

          <div className="field">
            <label htmlFor="auth-pw">Password</label>
            <input
              id="auth-pw"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder={mode === 'register' ? 'Min 6 characters' : 'Your password'}
              required
              minLength={6}
            />
          </div>

          {mode === 'register' && (
            <div className="field">
              <label htmlFor="auth-cpw">Confirm Password</label>
              <input
                id="auth-cpw"
                type="password"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                placeholder="Re-enter password"
                required
                minLength={6}
              />
            </div>
          )}

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Please wait...' : mode === 'login' ? 'Login' : 'Register'}
          </button>
        </form>

        <div className="auth-switch">
          {mode === 'login' ? (
            <span>Don't have an account? <button type="button" className="link-btn" onClick={switchMode}>Register</button></span>
          ) : (
            <span>Already have an account? <button type="button" className="link-btn" onClick={switchMode}>Login</button></span>
          )}
        </div>
      </div>
    </div>
  );
}
