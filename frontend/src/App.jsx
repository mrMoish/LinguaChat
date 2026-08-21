import { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [sessionId, setSessionId] = useState(null);
  const chatContainerRef = useRef(null);

  // 1. ИНИЦИАЛИЗАЦИЯ ПРИ СТАРТЕ
  useEffect(() => {
    const initChat = async () => {
      // Пробуем взять UUID из localStorage
      let currentSessionId = localStorage.getItem('translator_session_id');
      
      // Если UUID есть, пробуем загрузить историю текстов из localStorage (мгновенно)
      if (currentSessionId) {
        const savedHistory = localStorage.getItem('translator_chat_history');
        if (savedHistory) {
          try { setMessages(JSON.parse(savedHistory)); } catch (e) {}
        }
      }

      // Запрашиваем актуальную историю с бэкенда
      try {
        const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
        const headers = {};
        if (currentSessionId) headers['X-Session-Id'] = currentSessionId;

        const response = await fetch(`${backendUrl}/api/history`, { headers });
        if (response.ok) {
          const data = await response.json();
          // Сохраняем полученный UUID (если его не было, бэкенд сгенерировал новый)
          localStorage.setItem('translator_session_id', data.session_id);
          setSessionId(data.session_id);
          
          if (data.history && data.history.length > 0) {
            setMessages(data.history);
            localStorage.setItem('translator_chat_history', JSON.stringify(data.history));
          }
        }
      } catch (error) {
        console.error('Ошибка загрузки истории:', error);
      } finally {
        setIsInitializing(false);
      }
    };
    initChat();
  }, []);

  // 2. СОХРАНЕНИЕ И ПРОКРУТКА
  useEffect(() => {
    if (messages.length > 0) {
      localStorage.setItem('translator_chat_history', JSON.stringify(messages));
      const timer = setTimeout(() => {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [messages, isLoading]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage = { role: 'user', content: input };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput('');
    setIsLoading(true);

    try {
      const backendUrl = import.meta.env.VITE_BACKEND_URL || ''; 
      const headers = { 'Content-Type': 'application/json' };
      if (sessionId) headers['X-Session-Id'] = sessionId;
      
      const response = await fetch(`${backendUrl}/api/chat`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ message: input })
      });

      if (!response.ok) throw new Error('Network response was not ok');
      
      const data = await response.json();
      // Сохраняем новый UID, если бэкенд его обновил
      if (data.session_id) {
        localStorage.setItem('translator_session_id', data.session_id);
        setSessionId(data.session_id);
      }

      const aiMessage = { role: 'assistant', content: data.reply };
      const finalMessages = [...newMessages, aiMessage];
      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages));
    } catch (error) {
      console.error('Error:', error);
      const errorMessage = { role: 'assistant', content: 'Ошибка перевода. Попробуйте позже.' };
      setMessages([...newMessages, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  if (isInitializing) return <div className="app-container"></div>;

  return (
    <div className={`app-container ${messages.length === 0 ? 'empty-state-app' : 'chat-active-app'}`}>
      
      <button className="login-btn" aria-label="Войти">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
          <circle cx="12" cy="7" r="4"></circle>
        </svg>
        <span>Войти</span>
      </button>

      {messages.length > 0 && (
        <div className="chat-container" ref={chatContainerRef}>
          {messages.map((msg, idx) => (
            <div key={idx} className={`message-wrapper ${msg.role}`}>
              <div className={`message ${msg.role}`}>
                {msg.content}
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
      )}

      <div className="input-area">
        
        <button className="action-btn" aria-label="Прикрепить файл">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
          </svg>
        </button>

        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Введите текст для перевода..."
          rows={1}
          disabled={isLoading}
        />

        <button className="action-btn" aria-label="Голосовой ввод">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
        </button>

        <button 
          onClick={handleSend} 
          disabled={!input.trim() || isLoading} 
          className="send-btn"
          aria-label="Отправить"
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
    </div>
  );
}
export default App;
