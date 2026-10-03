import React, { useState } from 'react';

export default function LoginPage({ onLoginSuccess }) {
  // Tab control: 'login' | 'register'
  const [activeTab, setActiveTab] = useState('login');

  // Sign In Form State
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');

  // Create Account Form State
  const [companyName, setCompanyName] = useState('');
  const [registerEmail, setRegisterEmail] = useState('');
  const [registerPassword, setRegisterPassword] = useState('');

  // UI Feedback States
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  // 1. Handle Sign In
  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');
    setLoading(true);

    try {
      const response = await fetch('http://localhost:5000/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: loginEmail,
          password: loginPassword,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || 'Authentication failed');
      }

      // Save credentials to localStorage
      localStorage.setItem('jwt_token', data.token);
      localStorage.setItem('user_data', JSON.stringify(data.user));

      // Trigger parent callback
      if (onLoginSuccess) {
        onLoginSuccess(data.user, data.token);
      }
    } catch (err) {
      setError(err.message || 'Server connection failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // 2. Handle Client Account Registration
  const handleRegister = async (e) => {
    e.preventDefault();
    setError('');
    setSuccessMessage('');
    setLoading(true);

    try {
      const response = await fetch('http://localhost:5000/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_name: companyName,
          email: registerEmail,
          password: registerPassword,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || 'Registration failed');
      }

      // Success workflow: notify, pre-fill email, switch to login tab
      setSuccessMessage('Account created successfully! Please sign in.');
      setLoginEmail(registerEmail);
      setActiveTab('login');

      // Clear register state
      setCompanyName('');
      setRegisterEmail('');
      setRegisterPassword('');
    } catch (err) {
      setError(err.message || 'Failed to create account.');
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
            {activeTab === 'login'
              ? 'Access fleet tracking and logistics management'
              : 'Register your company for logistics services'}
          </p>
        </div>

        {/* Tab Selector: Sign In vs Create Account */}
        <div className="flex bg-slate-900 p-1 rounded-lg border border-slate-700">
          <button
            type="button"
            onClick={() => {
              setActiveTab('login');
              setError('');
              setSuccessMessage('');
            }}
            className={`flex-1 py-2 text-xs font-semibold rounded-md transition ${
              activeTab === 'login'
                ? 'bg-blue-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveTab('register');
              setError('');
              setSuccessMessage('');
            }}
            className={`flex-1 py-2 text-xs font-semibold rounded-md transition ${
              activeTab === 'register'
                ? 'bg-blue-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Create Account
          </button>
        </div>

        {/* Success Banner */}
        {successMessage && (
          <div className="bg-emerald-950/60 border border-emerald-500/50 text-emerald-300 text-sm p-3 rounded-lg flex items-center gap-2">
            <span>✅</span>
            <span>{successMessage}</span>
          </div>
        )}

        {/* Error Banner */}
        {error && (
          <div className="bg-red-950/60 border border-red-500/50 text-red-300 text-sm p-3 rounded-lg flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        {/* --- SIGN IN FORM --- */}
        {activeTab === 'login' && (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1">
                Email Address
              </label>
              <input
                type="email"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                placeholder="admin@difanlogistics.com"
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

        {/* --- CREATE ACCOUNT FORM --- */}
        {activeTab === 'register' && (
          <form onSubmit={handleRegister} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1">
                Company Name
              </label>
              <input
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="e.g., Summit Traders Ltd"
                required
                className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-1">
                Corporate Email
              </label>
              <input
                type="email"
                value={registerEmail}
                onChange={(e) => setRegisterEmail(e.target.value)}
                placeholder="info@summittraders.com"
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
                value={registerPassword}
                onChange={(e) => setRegisterPassword(e.target.value)}
                placeholder="At least 6 characters"
                required
                minLength={6}
                className="w-full px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-4 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-lg shadow-md transition duration-200 disabled:opacity-50 text-sm mt-2"
            >
              {loading ? 'Creating Account...' : 'Register Account'}
            </button>
          </form>
        )}

        {/* Demo Credentials Box */}
        {activeTab === 'login' && (
          <div className="bg-slate-900/60 p-3 rounded-lg border border-slate-700/50 text-xs text-slate-400 space-y-1">
            <p className="font-semibold text-slate-300">Default Admin Credentials:</p>
            <p>Email: <span className="text-slate-200 font-mono">admin@difanlogistics.com</span></p>
            <p>Password: <span className="text-slate-200 font-mono">AdminSecurePassword123!</span></p>
          </div>
        )}

      </div>
    </div>
  );
}