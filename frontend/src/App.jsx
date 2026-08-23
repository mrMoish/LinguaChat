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
            setMessages(parsed.filter(m => !m.isError && !m.isAssessment));
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
            // Помечаем сообщения флагом hideLesson, если язык не выбран
            const mappedHistory = data.history.map(m => ({
              ...m,
              hideLesson: !data.target_language_code
            }));
            setMessages(mappedHistory);
            localStorage.setItem('translator_chat_history', JSON.stringify(mappedHistory));
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
      const cleanMessages = messages.filter(m => !m.isError && !m.isAssessment);
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
      const lastIdx = finalMessages.length - 1;
      if (lastIdx >= 0 && finalMessages[lastIdx].role === 'user') {
        finalMessages[lastIdx] = {
          ...finalMessages[lastIdx],
          source_language: data.source_language || null
        };
      }

      const aiMessage = {
        role: 'assistant',
        content: data.reply,
        hideLesson: !data.target_language_code // Скрываем урок, если язык не выбран
      };
      finalMessages.push(aiMessage);

      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages.filter(m => !m.isError && !m.isAssessment)));
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

    const cleanMessages = messages.filter(m => !m.isError && !m.isAssessment);
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

  const generateLesson = async (idx) => {
    if (isLoading) return;

    const userMsg = messages[idx - 1];
    const aiMsg = messages[idx];
    if (!userMsg || userMsg.role !== 'user' || !aiMsg || aiMsg.role !== 'assistant') return;

    setIsLoading(true);

    try {
      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = { 'Content-Type': 'application/json' };
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/lesson`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ user_text: userMsg.content, ai_text: aiMsg.content })
      });

      if (!response.ok) throw new Error('Network response was not ok');

      const data = await response.json();

      if (data.action === 'assess') {
        const finalMessages = [...messages];
        finalMessages.push({
          role: 'assistant',
          isAssessment: true,
          texts: data.texts,
          currentLevelIndex: 1
        });
        setMessages(finalMessages);
      } else {
        const finalMessages = [...messages];
        finalMessages.push({ role: 'assistant', content: data.lesson, isLesson: true });
        setMessages(finalMessages);
        localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages.filter(m => !m.isError && !m.isAssessment)));
      }
    } catch (error) {
      console.error('Error:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      // Добавляем проверку: если не isLoading, то отправляем
      if (!isLoading) {
        handleSend();
      }
    }
  };

  const handleSliderChange = (msgIdx, levelIdx) => {
    const newMessages = [...messages];
    newMessages[msgIdx].currentLevelIndex = levelIdx;
    setMessages(newMessages);
  };

  const confirmLevel = async (msgIdx) => {
    const assessmentMsg = messages[msgIdx];
    const levelMap = ["0", "A1", "A2", "B1", "B2", "C1", "C2"];
    const selectedLevelStr = levelMap[assessmentMsg.currentLevelIndex];
    const selectedText = assessmentMsg.texts[assessmentMsg.currentLevelIndex];

    setIsLoading(true);
    try {
      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = { 'Content-Type': 'application/json' };
      if (sessionId) headers['X-Session-Id'] = sessionId;

      await fetch(`${backendUrl}/api/set_level`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ level: selectedLevelStr })
      });

      const newMessages = [...messages];
      newMessages[msgIdx] = {
        role: 'assistant',
        content: `Переведите:\n\n${selectedText}`,
        isLesson: true
      };
      setMessages(newMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(newMessages.filter(m => !m.isError && !m.isAssessment)));
    } catch (error) {
      console.error('Error saving level:', error);
    } finally {
      setIsLoading(false);
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
            const isLastMessage = idx === messages.length - 1;

            if (msg.isAssessment) {
              return (
                <div key={idx} className="message-wrapper assistant">
                  <div className="message assessment-card">

                    {/* Обернули текст и ползунок */}
                    <div className="assessment-content-wrapper">
                      <div className="assessment-text-area">
                        {msg.currentLevelIndex === 0 ? (
                          <p className="beginner-text">Я только начал учить целевой язык</p>
                        ) : (
                          <div style={{ whiteSpace: 'pre-wrap' }}>
                            {msg.texts[msg.currentLevelIndex]}
                          </div>
                        )}
                      </div>

                      <div className="assessment-slider">
                        {[6, 5, 4, 3, 2, 1, 0].map((levelIdx) => (
                          <div
                            key={levelIdx}
                            className={`slider-dot ${msg.currentLevelIndex === levelIdx ? 'active' : ''}`}
                            onClick={() => handleSliderChange(idx, levelIdx)}
                          ></div>
                        ))}
                      </div>
                    </div>

                    {/* Нижний блок с кнопкой */}
                    <div className="assessment-footer">
                      <span className="assessment-prompt-text">Выберите свой уровень языка</span>
                      <button
                        className="confirm-level-btn"
                        onClick={() => confirmLevel(idx)}
                        disabled={isLoading}
                      >
                        Это мой уровень
                      </button>
                    </div>

                  </div>
                </div>
              );
            }
            return (
              <div key={idx} className={`message-wrapper ${msg.role}`}>
                <div className={`message ${msg.role} ${msg.isError ? 'error-message' : ''} ${msg.isLesson ? 'lesson-message' : ''}`}>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>

                  {msg.isError && (
                    <button className="retry-btn" onClick={() => handleRetry(idx)} disabled={isLoading}>
                      Попробовать снова
                    </button>
                  )}
                </div>

                {msg.role === 'user' && msg.source_language && (
                  <div className="source-language-tag">{msg.source_language}</div>
                )}

                {msg.role === 'assistant' && !msg.isError && !msg.isLesson && !msg.hideLesson && isLastMessage && !isLoading && (
                  <button className="lesson-btn" onClick={() => generateLesson(idx)} disabled={isLoading}>
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