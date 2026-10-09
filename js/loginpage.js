import React, { useState } from 'react';

const readJson = async (response) => {
  const text = await response.text();
  if (!text) {
    throw new Error(response.ok ? 'The server returned an empty response.' : 'The server is unavailable. Please try again shortly.');
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new Error('The server returned an unexpected response. Please try again shortly.');
  }
};

export default function LoginPage({ onLoginSuccess }) {
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [pendingToken, setPendingToken] = useState('');
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch(window.DifanApp.apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: loginEmail,
          password: loginPassword,
        }),
      });

      const data = await readJson(response);

      if (!response.ok) {
        throw new Error(data.message || 'Authentication failed');
      }

      if (data.user.must_change_password) {
        setPendingToken(data.token);
        setMustChangePassword(true);
        return;
      }

      localStorage.setItem('jwt_token', data.token);
      localStorage.setItem('user_data', JSON.stringify(data.user));

      if (onLoginSuccess) {
        onLoginSuccess(data.user, data.token);
      }
    } catch (err) {
      setError(err.message || 'Server connection failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setError('');
    if (newPassword !== confirmPassword) {
      setError('The passwords do not match.');
      return;
    }
    setLoading(true);

    try {
      const response = await fetch(window.DifanApp.apiUrl('/api/auth/change-password'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${pendingToken}`,
        },
        body: JSON.stringify({ password: newPassword }),
      });
      const data = await readJson(response);
      if (!response.ok) {
        throw new Error(data.message || 'Password change failed.');
      }

      localStorage.setItem('jwt_token', data.token);
      localStorage.setItem('user_data', JSON.stringify(data.user));
      if (onLoginSuccess) onLoginSuccess(data.user, data.token);
    } catch (err) {
      setError(err.message || 'Unable to change your password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-slate-800 rounded-xl shadow-2xl border border-slate-700 p-8 space-y-6">
        
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-extrabold text-white tracking-tight">
            Difan <span className="text-blue-500">Logistics</span>
          </h1>
          <p className="text-slate-400 text-sm">
            {mustChangePassword
              ? 'Change your temporary password to continue'
              : 'Sign in with the account created for you by Difan HR'}
          </p>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="bg-red-950/60 border border-red-500/50 text-red-300 text-sm p-3 rounded-lg flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {mustChangePassword ? (
          <form onSubmit={handlePasswordChange} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1">
                New password (12 characters minimum)
              </label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={12}
                autoComplete="new-password"
                required
                className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1">
                Confirm new password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                minLength={12}
                autoComplete="new-password"
                required
                className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg shadow-md transition duration-200 disabled:opacity-50 text-sm mt-2"
            >
              {loading ? 'Changing password...' : 'Change password'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1">
                Username or email address
              </label>
              <input
                type="text"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                autoComplete="username"
                placeholder="DifanMain or name@company.com"
                required
                className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1">
                Password
              </label>
              <input
                type="password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                placeholder="••••••••••••"
                required
                className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg shadow-md transition duration-200 disabled:opacity-50 text-sm mt-2"
            >
              {loading ? 'Authenticating...' : 'Sign In'}
            </button>
          </form>
        )}

      </div>
    </div>
  );
}