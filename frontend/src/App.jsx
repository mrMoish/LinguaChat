import { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [sessionId, setSessionId] = useState(null);
  const chatContainerRef = useRef(null);
  const [showAttachMenu, setShowAttachMenu] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);


  // Создаем ссылку на обертку скрепки
  const menuRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    const initChat = async () => {
      let currentSessionId = localStorage.getItem('translator_session_id');

      // 1. Сначала мгновенно загружаем из localStorage
      if (currentSessionId) {
        const savedHistory = localStorage.getItem('translator_chat_history');
        if (savedHistory) {
          try {
            const parsed = JSON.parse(savedHistory);
            setMessages(parsed.filter(m => !m.isError && !m.isAssessment));
          } catch (e) {}
        }
      }

      // 2. Затем синхронизируемся с сервером
      try {
        const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
        const headers = {};
        if (currentSessionId) headers['X-Session-Id'] = currentSessionId;

        const response = await fetch(`${backendUrl}/api/history`, { headers });
        if (response.ok) {
          const data = await response.json();
          localStorage.setItem('translator_session_id', data.session_id);
          setSessionId(data.session_id);

          // 3. Переписываем локальную историю данными с сервера
          // (сервер уже удалил "висящий" урок и вернул флаги isLesson/isEvaluation)
          const mappedHistory = data.history.map(m => ({
            ...m,
            hideLesson: !data.target_language_code
          }));

          setMessages(mappedHistory);
          localStorage.setItem('translator_chat_history', JSON.stringify(mappedHistory));
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

  // 3. ОБРАБОТКА ПЕРЕКЛЮЧЕНИЯ ВКЛАДОК
  useEffect(() => {
    const handleVisibilityChange = async () => {
      // Если вкладка снова стала видимой
      if (document.visibilityState === 'visible') {
        // Проверяем, является ли последнее сообщение активным уроком
        if (messages.length > 0 && messages[messages.length - 1].isLesson) {
          try {
            const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
            const headers = {};
            if (sessionId) headers['X-Session-Id'] = sessionId;

            // Отправляем запрос на удаление урока и сохранение в логи
            await fetch(`${backendUrl}/api/abandon_lesson`, {
              method: 'POST',
              headers: headers
            });

            // Удаляем урок из интерфейса и localStorage
            const newMessages = messages.slice(0, -1);
            setMessages(newMessages);
            localStorage.setItem('translator_chat_history', JSON.stringify(newMessages));
          } catch (error) {
            console.error('Error abandoning lesson:', error);
          }
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [messages, sessionId]);

  // 3. ЗАКРЫТИЕ МЕНЮ ПО КЛИКУ ВНЕ ЕГО
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Если кликнули не внутри обертки меню (menuRef.current)
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setShowAttachMenu(false);
      }
    };

    // Вешаем слушатель на весь документ при монтировании
    document.addEventListener("mousedown", handleClickOutside);

    // Убираем слушатель при размонтировании
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

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

  // Проверка ответа на мини-урок
  const checkLessonAnswer = async (answerText, lessonMsg, messagesState) => {
    setIsLoading(true);
    try {
      // Сразу отображаем ответ пользователя в чате
      const userMessage = { role: 'user', content: answerText };
      const messagesWithAnswer = [...messagesState, userMessage];
      setMessages(messagesWithAnswer);

      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = { 'Content-Type': 'application/json' };
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/check_lesson`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ lesson_text: lessonMsg.content, user_answer: answerText })
      });

      if (!response.ok) throw new Error('Network response was not ok');

      const data = await response.json();
      const evaluationMessage = {
        role: 'assistant',
        content: data.evaluation,
        isEvaluation: true // Помечаем, чтобы стилизовать
      };

      const finalMessages = [...messagesWithAnswer, evaluationMessage];
      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages.filter(m => !m.isError && !m.isAssessment)));
    } catch (error) {
      console.error('Error checking lesson:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const cleanMessages = messages.filter(m => !m.isError && !m.isAssessment);
    const lastMessage = cleanMessages[cleanMessages.length - 1];

    const currentInput = input;
    setInput('');

    // Если последнее сообщение — это активный мини-урок, отправляем на проверку
    if (lastMessage && lastMessage.isLesson) {
      await checkLessonAnswer(currentInput, lastMessage, cleanMessages);
    } else {
      // Обычный перевод
      const userMessage = { role: 'user', content: currentInput, source_language: null };
      const newMessages = [...cleanMessages, userMessage];
      setMessages(newMessages);
      await sendRequest(currentInput, newMessages);
    }
  };

  const handleFileChange = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    setShowAttachMenu(false); // Закрываем меню
    setIsLoading(true);

    // Создаем сообщение пользователя и пустое сообщение для ИИ (которое будем заполнять)
    const userMessage = { role: 'user', content: `📄 Загружен файл: ${file.name}` };
    const aiMessage = { role: 'assistant', content: '' };

    // Обновляем состояние
    setMessages(prev => [...prev, userMessage, aiMessage]);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = {};
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/upload_pdf`, {
        method: 'POST',
        headers: headers,
        body: formData
      });

      if (!response.ok) throw new Error('Upload failed');

      // Читаем потоковый ответ
      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // Декодируем кусок текста
        const chunkText = decoder.decode(value, { stream: true });

        // Добавляем текст к последнему сообщению (переводу)
        setMessages(prev => {
          const newMsgs = [...prev];
          newMsgs[newMsgs.length - 1] = {
            ...newMsgs[newMsgs.length - 1],
            content: newMsgs[newMsgs.length - 1].content + chunkText
          };
          return newMsgs;
        });
      }

      // Сохраняем финальный результат в localStorage
      setMessages(prev => {
        localStorage.setItem('translator_chat_history', JSON.stringify(prev.filter(m => !m.isError && !m.isAssessment)));
        return prev;
      });

    } catch (error) {
      console.error('Error uploading file:', error);
      setMessages(prev => {
        const newMsgs = [...prev];
        newMsgs[newMsgs.length - 1] = {
          ...newMsgs[newMsgs.length - 1],
          content: 'Ошибка при обработке файла.',
          isError: true
        };
        return newMsgs;
      });
    } finally {
      setIsLoading(false);
      event.target.value = null; // Сбрасываем инпут
    }
  };

  const startRecording = async () => {
    try {
      // Запрашиваем доступ к микрофону
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Останавливаем все потоки микрофона
        stream.getTracks().forEach(track => track.stop());

        // Создаем аудиофайл
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await sendAudioToServer(audioBlob);
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Ошибка доступа к микрофону:", err);
      alert("Нет доступа к микрофону. Разрешите доступ в настройках браузера.");
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  };

  const sendAudioToServer = async (blob) => {
    setIsLoading(true);

    const userMessage = { role: 'user', content: '🎤 Голосовое сообщение', source_language: 'Голос' };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);

    try {
      const formData = new FormData();
      formData.append('file', blob, 'audio.webm');

      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = {};
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/audio_translate`, {
        method: 'POST',
        headers: headers,
        body: formData
      });

      if (!response.ok) throw new Error('Audio translation failed');
      const data = await response.json();

      const aiMessage = { role: 'assistant', content: data.reply };
      const finalMessages = [...newMessages, aiMessage];
      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages));
    } catch (error) {
      console.error('Audio error:', error);
      const errorMessage = { role: 'assistant', content: 'Ошибка перевода аудио.', isError: true };
      const finalMessages = [...newMessages, errorMessage];
      setMessages(finalMessages);
    } finally {
      setIsLoading(false);
    }
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
    if (!aiMsg || aiMsg.role !== 'assistant') return;

    // Проверяем, является ли сообщение оценкой за урок
    const useHistory = aiMsg.isEvaluation || false;

    setIsLoading(true);

    try {
      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = { 'Content-Type': 'application/json' };
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/lesson`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          user_text: userMsg?.content || "",
          ai_text: aiMsg.content,
          use_history: useHistory // Отправляем лаг!
        })
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

  const dismissLesson = async (msgIdx) => {
    const newMessages = [...messages];
    newMessages.splice(msgIdx, 1);
    setMessages(newMessages);
    localStorage.setItem('translator_chat_history', JSON.stringify(newMessages.filter(m => !m.isError && !m.isAssessment)));

    // Уведомляем бэкенд, чтобы он удалил урок из базы и сохранил в логи
    try {
      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = {};
      if (sessionId) headers['X-Session-Id'] = sessionId;
      await fetch(`${backendUrl}/api/abandon_lesson`, {
        method: 'POST',
        headers: headers
      });
    } catch (e) {
      console.error('Error abandoning lesson on server:', e);
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
                          <p className="beginner-text">Я только начал учить язык</p>
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

                  {/* Кнопка закрытия урока (только для последнего сообщения) */}
                  {msg.isLesson && isLastMessage && (
                    <button className="lesson-close-btn" onClick={() => dismissLesson(idx)} aria-label="Закрыть">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                      </svg>
                    </button>
                  )}
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
      {/* Обертка для скрепки и меню */}
      <div className="paperclip-wrapper" ref={menuRef}>
        <button className="action-btn" aria-label="Прикрепить файл" onClick={() => setShowAttachMenu(!showAttachMenu)}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
          </svg>
        </button>

        {/* Само меню */}
        {showAttachMenu && (
          <div className="attachment-menu">
            <div className="menu-item" onClick={() => { console.log("Медиатека"); setShowAttachMenu(false); }}>
              <span>Медиатека</span>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <circle cx="8.5" cy="8.5" r="1.5"></circle>
                <polyline points="21 15 16 10 5 21"></polyline>
              </svg>
            </div>

            <div className="menu-item" onClick={() => { console.log("Снимок"); setShowAttachMenu(false); }}>
              <span>Сделать снимок</span>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                <circle cx="12" cy="13" r="4"></circle>
              </svg>
            </div>

            <div className="menu-item" onClick={() => {
                setShowAttachMenu(false);
                fileInputRef.current.click();
            }}>
              <span>Выбор файлов</span>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
              </svg>
            </div>
          </div>
        )}
      </div>
      {/* Скрытый инпут для загрузки файлов */}
      <input
        type="file"
        accept="application/pdf"
        ref={fileInputRef}
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Введите текст..."
          rows={1}
        />

        <button
          className={`action-btn mic-btn ${isRecording ? 'recording' : ''}`}
          onClick={isRecording ? stopRecording : startRecording}
          aria-label="Голосовой ввод"
        >
          {isRecording ? (
            <span className="rec-dot"></span>
          ) : (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
              <line x1="12" y1="19" x2="12" y2="23"></line>
              <line x1="8" y1="23" x2="16" y2="23"></line>
            </svg>
          )}
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