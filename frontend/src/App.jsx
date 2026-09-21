import { useState, useRef, useEffect } from 'react';
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
  const fileInputRef = useRef(null);

  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isAppInstalled, setIsAppInstalled] = useState(false);

  const backendUrl = import.meta.env.VITE_BACKEND_URL || '';

  // Синхронизация истории с сервером
  // Синхронизация с сервером: БД — источник истины.
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
            // Полностью заменяем локальную историю актуальной из БД
            setMessages(data.history);
            // Принудительно обновляем localStorage актуальной историей
            localStorage.setItem('translator_chat_history', JSON.stringify(data.history));
          }
        }
      } catch (error) {
        console.error('Ошибка синхронизации истории:', error);
      }
    };
    syncHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Скролл вниз
  useEffect(() => {
    if (messages.length > 0) {
      try {
        // ВАЖНО: Убираем картинки (Base64) перед сохранением в localStorage,
        // чтобы не превысить лимит 5МБ и приложение не упало с белым экраном.
        const cleanMessages = messages.filter(m => !m.isError).map(m => {
          const { image, ...rest } = m; // Вырезаем поле image
          return rest;
        });
        localStorage.setItem('translator_chat_history', JSON.stringify(cleanMessages));
      } catch (e) {
        console.error("Ошибка сохранения в localStorage (возможно, превышен лимит)", e);
      }

      const timer = setTimeout(() => {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [messages, isLoading]);

  // PWA логика
  useEffect(() => {
    if (window.matchMedia('(display-mode: standalone)').matches) {
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

  // Универсальная функция отправки сообщения (Текст или Фото)
  const sendMessage = async (text, file) => {
    if (isLoading || (!text && !file)) return;
    setIsLoading(true);

    let imagePreview = null;
    if (file) {
      if (file.size > 5 * 1024 * 1024) { alert("Файл слишком большой (макс 5МБ)."); setIsLoading(false); return; }
      if (!file.type.startsWith("image/")) { alert("Можно отправлять только изображения."); setIsLoading(false); return; }

      imagePreview = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.readAsDataURL(file);
      });
    }

    const userMessage = { role: 'user', content: text || '', image: imagePreview };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput('');

    const formData = new FormData();
    if (text) formData.append('text', text);
    if (file) formData.append('file', file);

    try {
      const response = await fetch(`${backendUrl}/api/message`, {
        method: 'POST',
        headers: { ...(sessionId ? { 'X-Session-Id': sessionId } : {}) },
        body: formData
      });
      if (!response.ok) throw new Error('Network error');
      const data = await response.json();

      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem('translator_session_id', data.session_id);
      }

      setMessages([...newMessages, { role: 'assistant', content: data.translation }]);
    } catch (error) {
      console.error('Ошибка отправки:', error);
      setMessages([...newMessages, { role: 'assistant', content: 'Не получилось отправить. Попробуйте позже.', isError: true }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    await sendMessage(input, null);
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
                    {messages.map((msg, idx) => {
            // Статичный наклон для Polaroid (чтобы не прыгал при ререндере)
            const rotations = ['-2deg', '1.5deg', '-1deg', '2deg'];
            const rotation = rotations[idx % 4];

            return (
              <div key={idx} className={`message-wrapper ${msg.role}`}>
                {/* Если есть фото — рендерим Polaroid вне облачка */}
                {msg.image && (
                  <div className="polaroid" style={{ transform: `rotate(${rotation})` }}>
                    <img src={msg.image} alt="Upload" />
                  </div>
                )}

                {/* Обычное текстовое сообщение рендерится, только если есть текст */}
                {msg.content && (
                  <div className={`message ${msg.role} ${msg.isError ? 'error-message' : ''}`}>
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
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
            <p>Введите текст или отправьте фото для перевода.</p>
          </div>
        )
      )}

      <div className="input-area">
        <input
          type="file"
          accept="image/*"
          ref={fileInputRef}
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files[0];
            if (file) sendMessage(null, file);
            e.target.value = null;
          }}
        />
        <button className="action-btn" onClick={() => fileInputRef.current.click()} disabled={isLoading} aria-label="Прикрепить фото">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
          </svg>
        </button>

        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Сообщение..."
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