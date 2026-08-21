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
    // ... тут без изменений JSX ...
  );
}
export default App;
