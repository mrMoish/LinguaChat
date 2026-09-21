import { useState, useRef, useEffect, useLayoutEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './App.css';

function loadCachedMessages() {
  try {
    const cached = localStorage.getItem('translator_chat_history');
    if (cached) {
      const parsed = JSON.parse(cached);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch (e) {}
  return [];
}

function App() {
  const [messages, setMessages] = useState(loadCachedMessages);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('translator_session_id') || null);

  const chatContainerRef = useRef(null);
  const isFirstScrollRef = useRef(true);

  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isAppInstalled, setIsAppInstalled] = useState(false);

  const backendUrl = import.meta.env.VITE_BACKEND_URL || '';

  // Фоновая синхронизация с сервером — только если сессия уже существует.
  useEffect(() => {
    if (!sessionId) return;
    const syncHistory = async () => {
      try {
        const response = await fetch(`${backendUrl}/api/history`, {
          headers: { 'X-Session-Id': sessionId }
        });
        if (response.ok) {
          const data = await response.json();
          if (data.history) {
            setMessages(data.history);
          }
        }
      } catch (error) {
        console.error('Ошибка синхронизации истории:', error);
      }
    };
    syncHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Мгновенно ставим правильную позицию скролла ДО того, как браузер отрисует кадр —
  // без этого при обновлении страницы виден скачок: сначала верх, потом рывок вниз.
  useLayoutEffect(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'auto' });
  }, []);

  useEffect(() => {
    if (messages.length > 0) {
      localStorage.setItem('translator_chat_history', JSON.stringify(messages.filter(m => !m.isError)));
    }
    if (isFirstScrollRef.current) {
      // Позиция уже выставлена мгновенно в useLayoutEffect выше — плавный скролл здесь не нужен.
      isFirstScrollRef.current = false;
      return;
    }
    const timer = setTimeout(() => {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
    }, 100);
    return () => clearTimeout(timer);
  }, [messages, isLoading]);

  useEffect(() => {
    if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
      setIsAppInstalled(true);
      return;
    }
    const handleBeforeInstallPrompt = (e) => { e.preventDefault(); setDeferredPrompt(e); };
    const handleAppInstalled = () => { setIsAppInstalled(true); setDeferredPrompt(null); };
    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    window.addEventListener('appinstalled', handleAppInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  }, []);

  const handleInstallClick = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') setIsAppInstalled(true);
    setDeferredPrompt(null);
  };

  const sendMessage = async (text) => {
    if (!text.trim() || isLoading) return;
    setIsLoading(true);
    const userMessage = { role: 'user', content: text };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);

    try {
      const response = await fetch(`${backendUrl}/api/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(sessionId ? { 'X-Session-Id': sessionId } : {}) },
        body: JSON.stringify({ message: text })
      });
      if (!response.ok) throw new Error('Network error');
      const data = await response.json();

      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem('translator_session_id', data.session_id);
      }

      setMessages([...newMessages, { role: 'assistant', content: data.translation }]);
      return data;
    } catch (error) {
      console.error('Ошибка отправки:', error);
      setMessages([...newMessages, { role: 'assistant', content: 'Не получилось перевести. Попробуйте позже.', isError: true }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const text = input;
    setInput('');
    await sendMessage(text);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading) handleSend();
    }
  };

  return (
    <div className={`app-container ${messages.length === 0 ? 'empty-state-app' : 'chat-active-app'}`}>
      {!isAppInstalled && deferredPrompt && (
        <button className="login-btn" onClick={handleInstallClick} aria-label="Установить">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>Установить</span>
        </button>
      )}

      {messages.length > 0 ? (
        <div className="chat-container" ref={chatContainerRef}>
          {messages.map((msg, idx) => (
            <div key={idx} className={`message-wrapper ${msg.role}`}>
              <div className={`message ${msg.role} ${msg.isError ? 'error-message' : ''}`}>
                <div className="markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || ''}</ReactMarkdown>
                </div>
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="message-wrapper assistant">
              <div className="message assistant typing">
                <span></span><span></span><span></span>
              </div>
            </div>
          )}
        </div>
      ) : (
        !isLoading && (
          <div className="empty-state">
            <p>Введите текст на русском или английском — переведу.</p>
          </div>
        )
      )}

      <div className="input-area">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Введите текст..."
          rows={1}
        />

        <div className="send-wrapper">
          <button onClick={handleSend} disabled={!input.trim() || isLoading} className="send-btn" aria-label="Отправить">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
