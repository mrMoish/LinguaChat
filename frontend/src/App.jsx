import { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [sessionId, setSessionId] = useState(null);
  const chatContainerRef = useRef(null);

  useEffect(() => {
    const initChat = async () => {
      let currentSessionId = localStorage.getItem('translator_session_id');
      
      if (currentSessionId) {
        const savedHistory = localStorage.getItem('translator_chat_history');
        if (savedHistory) {
          try { 
            const parsed = JSON.parse(savedHistory);
            setMessages(parsed.filter(m => !m.isError)); 
          } catch (e) {}
        }
      }

      try {
        const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
        const headers = {};
        if (currentSessionId) headers['X-Session-Id'] = currentSessionId;

        const response = await fetch(`${backendUrl}/api/history`, { headers });
        if (response.ok) {
          const data = await response.json();
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

  useEffect(() => {
    if (messages.length > 0) {
      const cleanMessages = messages.filter(m => !m.isError);
      localStorage.setItem('translator_chat_history', JSON.stringify(cleanMessages));
      
      const timer = setTimeout(() => {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [messages, isLoading]);

  const sendRequest = async (text, messagesState) => {
    setIsLoading(true);
    try {
      const backendUrl = import.meta.env.VITE_BACKEND_URL || ''; 
      const headers = { 'Content-Type': 'application/json' };
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/chat`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ message: text })
      });

      if (!response.ok) throw new Error('Network response was not ok');
      
      const data = await response.json();
      if (data.session_id) {
        localStorage.setItem('translator_session_id', data.session_id);
        setSessionId(data.session_id);
      }

      const finalMessages = [...messagesState];
      // Обновляем последнее сообщение пользователя, добавляя исходный язык
      const lastIdx = finalMessages.length - 1;
      if (lastIdx >= 0 && finalMessages[lastIdx].role === 'user') {
        finalMessages[lastIdx] = {
          ...finalMessages[lastIdx],
          source_language: data.source_language || null
        };
      }

      const aiMessage = { role: 'assistant', content: data.reply };
      finalMessages.push(aiMessage);
      
      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages));
    } catch (error) {
      console.error('Error:', error);
      const errorMessage = {
        role: 'assistant',
        content: 'Ошибка перевода. Попробуйте позже.',
        isError: true,
        originalText: text
      };
      const finalMessages = [...messagesState, errorMessage];
      setMessages(finalMessages);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const cleanMessages = messages.filter(m => !m.isError);
    const userMessage = { role: 'user', content: input, source_language: null };
    const newMessages = [...cleanMessages, userMessage];
    setMessages(newMessages);

    const currentInput = input;
    setInput('');

    await sendRequest(currentInput, newMessages);
  };

  const handleRetry = async (errorIndex) => {
    if (isLoading) return;
    
    const errorMsgObj = messages[errorIndex];
    if (!errorMsgObj.isError) return;

    const messagesWithoutError = messages.slice(0, errorIndex);
    setMessages(messagesWithoutError);

    await sendRequest(errorMsgObj.originalText, messagesWithoutError);
  };

  // Генерация мини-урока
  const generateLesson = async (idx) => {
    if (isLoading) return;
    
    const userMsg = messages[idx - 1];
    const aiMsg = messages[idx];
    
    if (!userMsg || userMsg.role !== 'user' || !aiMsg || aiMsg.role !== 'assistant') return;

    setIsLoading(true); // Включаем загрузку (появятся три точки внизу)

    try {
      const backendUrl = import.meta.env.VITE_BACKEND_URL || ''; 
      const headers = { 'Content-Type': 'application/json' };
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/lesson`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ 
          user_text: userMsg.content, 
          ai_text: aiMsg.content 
        })
      });

      if (!response.ok) throw new Error('Network response was not ok');
      
      const data = await response.json();
      
      // Просто добавляем урок в конец массива сообщений
      const finalMessages = [...messages];
      finalMessages.push({ role: 'assistant', content: data.lesson, isLesson: true });
      
      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages.filter(m => !m.isError)));
    } catch (error) {
      console.error('Error:', error);
      const finalMessages = [...messages];
      finalMessages.push({ role: 'assistant', content: 'Не удалось загрузить урок.', isError: true });
      setMessages(finalMessages);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { 
      e.preventDefault(); 
      handleSend(); 
    }
  };

  return (
    <div className={`app-container ${messages.length === 0 ? 'empty-state-app' : 'chat-active-app'}`}>
      
      <button className="login-btn" aria-label="Войти">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
          <circle cx="12" cy="7" r="4"></circle>
        </svg>
        <span>Войти</span>
      </button>

      {messages.length > 0 ? (
        <div className="chat-container" ref={chatContainerRef}>
            {messages.map((msg, idx) => {
            // Проверяем, последнее ли это сообщение в массиве
            const isLastMessage = idx === messages.length - 1;
            
            return (
              <div key={idx} className={`message-wrapper ${msg.role}`}>
                
                {/* Само сообщение (пузырь) */}
                <div className={`message ${msg.role} ${msg.isError ? 'error-message' : ''} ${msg.isLesson ? 'lesson-message' : ''}`}>
                  <div style={{ whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </div>
                  
                  {msg.isError && (
                    <button 
                      className="retry-btn" 
                      onClick={() => handleRetry(idx)}
                      disabled={isLoading}
                    >
                      Попробовать снова
                    </button>
                  )}
                </div>

                {/* Исходный язык ВНЕ сообщения, но ВНУТРИ обертки (под сообщением пользователя) */}
                {msg.role === 'user' && msg.source_language && (
                  <div className="source-language-tag">
                    {msg.source_language}
                  </div>
                )}

                {/* Кнопка Мини-урок ВНЕ сообщения, только для последнего ответа ИИ */}
                {msg.role === 'assistant' && !msg.isError && !msg.isLesson && isLastMessage && !isLoading && (
                  <button 
                    className="lesson-btn" 
                    onClick={() => generateLesson(idx)}
                    disabled={isLoading}
                  >
                    🎓 Мини-урок
                  </button>
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
            <p>Пришли то, что тебе не понятно, или скажи, какой язык хочешь изучать.</p>
          </div>
        )
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
          placeholder="Введите текст..."
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
