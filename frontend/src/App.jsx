import { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [sessionId, setSessionId] = useState(null);
  const chatContainerRef = useRef(null);

  // PWA установки
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isAppInstalled, setIsAppInstalled] = useState(false);

  // Запись аудио
  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  // Файлы
  const fileInputRef = useRef(null);

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

          // 1. Получаем сырую историю из базы
          const rawHistory = data.history.map(m => ({ ...m, hideLesson: !data.target_language_code }));

          // 2. Обрабатываем оценки: переносим данные на сообщение пользователя, а сообщение ИИ скрываем
          for (let i = 0; i < rawHistory.length; i++) {
            if (rawHistory[i].role === 'assistant' && rawHistory[i].isEvaluation) {
              try {
                const evalData = JSON.parse(rawHistory[i].content);
                rawHistory[i].evalData = evalData;

                if (i > 0 && rawHistory[i-1].role === 'user') {
                  rawHistory[i-1].evalData = evalData;
                  // Показываем ссылку "объяснить" только для Хорошо и Понятно
                  if (evalData.grade === 'Хорошо' || evalData.grade === 'Понятно') {
                    rawHistory[i-1].showExplainLink = true;
                  }
                }
              } catch (e) {}
            }
          }

          // 3. Фильтруем: оставляем сообщение ИИ только если оценка "Не понятно"
          const visibleHistory = rawHistory.filter(m => {
            if (m.role === 'assistant' && m.isEvaluation && m.evalData) {
              if (m.evalData.grade === 'Не понятно') {
                m.content = m.evalData.correct_answer;
                return true; // Оставляем
              }
              return false; // Скрываем все остальные оценки (Идеально, Хорошо, Понятно)
            }
            return true;
          });

          setMessages(visibleHistory);
          localStorage.setItem('translator_chat_history', JSON.stringify(visibleHistory));
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

  useEffect(() => {
    const handleVisibilityChange = async () => {
      if (document.visibilityState === 'visible') {
        if (messages.length > 0 && messages[messages.length - 1].isLesson) {
          try {
            const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
            const headers = {};
            if (sessionId) headers['X-Session-Id'] = sessionId;

            await fetch(`${backendUrl}/api/abandon_lesson`, {
              method: 'POST',
              headers: headers
            });

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

  // PWA Logic
  useEffect(() => {
    if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true) {
      setIsAppInstalled(true);
      return;
    }

    const handleBeforeInstallPrompt = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };

    const handleAppInstalled = () => {
      setIsAppInstalled(true);
      setDeferredPrompt(null);
    };

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
    if (outcome === 'accepted') {
      setIsAppInstalled(true);
    }
    setDeferredPrompt(null);
  };

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
        hideLesson: !data.target_language_code
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

  const checkLessonAnswer = async (answerText, lessonMsg, messagesState) => {
    setIsLoading(true);
    try {
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

      const finalMessages = [...messagesWithAnswer];

      // Прикрепляем оценку к сообщению пользователя
      finalMessages[finalMessages.length - 1].evalData = {
        grade: data.grade,
        correct_answer: data.correct_answer
      };
      finalMessages[finalMessages.length - 1].showExplainLink = (data.grade === 'Хорошо' || data.grade === 'Понятно');

      // Если "Не понятно", сразу добавляем сообщение с правильным ответом
      if (data.grade === 'Не понятно') {
        finalMessages.push({
          role: 'assistant',
          content: data.correct_answer,
          isEvaluation: true,
          evalData: { grade: data.grade, correct_answer: data.correct_answer }
        });
      }

      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages.filter(m => !m.isError && !m.isAssessment)));
    } catch (error) {
      console.error('Error checking lesson:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Добавление/удаление сообщения с правильным ответом
  const toggleExplanation = (userMsgIdx) => {
    const newMessages = [...messages];
    const userMsg = newMessages[userMsgIdx];
    if (!userMsg.evalData) return;

    const aiMsgIdx = userMsgIdx + 1;
    const existingAiMsg = newMessages[aiMsgIdx];

    // Если сообщение ИИ уже существует и содержит правильный ответ -> скрываем его
    if (existingAiMsg && existingAiMsg.isEvaluation && existingAiMsg.content.includes("Правильный ответ:")) {
      newMessages.splice(aiMsgIdx, 1); // Удаляем сообщение
      userMsg.showExplainLink = true; // Возвращаем ссылку "объяснить"
    } else {
      // Иначе добавляем сообщение с правильным ответом
      const newAiMessage = {
        role: 'assistant',
        content: userMsg.evalData.correct_answer,
        isEvaluation: true,
        evalData: userMsg.evalData
      };
      newMessages.splice(userMsgIdx + 1, 0, newAiMessage); // Вставляем после сообщения пользователя
      userMsg.showExplainLink = false; // Прячем ссылку
    }

    setMessages(newMessages);
    localStorage.setItem('translator_chat_history', JSON.stringify(newMessages.filter(m => !m.isError && !m.isAssessment)));
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const cleanMessages = messages.filter(m => !m.isError && !m.isAssessment);
    const lastMessage = cleanMessages[cleanMessages.length - 1];

    const currentInput = input;
    setInput('');

    if (lastMessage && lastMessage.isLesson) {
      await checkLessonAnswer(currentInput, lastMessage, cleanMessages);
    } else {
      const userMessage = { role: 'user', content: currentInput, source_language: null };
      const newMessages = [...cleanMessages, userMessage];
      setMessages(newMessages);
      await sendRequest(currentInput, newMessages);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading) {
        handleSend();
      }
    }
  };

  // === ОБРАБОТКА ФАЙЛОВ (PDF и Фото) ===

  const processPdf = async (file) => {
    setIsLoading(true);
    const userMessage = { role: 'user', content: `📄 Загружен файл: ${file.name}` };
    const aiMessage = { role: 'assistant', content: '' };
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

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunkText = decoder.decode(value, { stream: true });

        setMessages(prev => {
          const newMsgs = [...prev];
          newMsgs[newMsgs.length - 1] = {
            ...newMsgs[newMsgs.length - 1],
            content: newMsgs[newMsgs.length - 1].content + chunkText
          };
          return newMsgs;
        });
      }

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
    }
  };

  const processImage = async (file) => {
    setIsLoading(true);
    const userMessage = { role: 'user', content: '📷 Фото для перевода', source_language: 'Фото' };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
      const headers = {};
      if (sessionId) headers['X-Session-Id'] = sessionId;

      const response = await fetch(`${backendUrl}/api/image_translate`, {
        method: 'POST',
        headers: headers,
        body: formData
      });

      if (!response.ok) throw new Error('Image translation failed');
      const data = await response.json();

      const aiMessage = { role: 'assistant', content: data.reply };
      const finalMessages = [...newMessages, aiMessage];
      setMessages(finalMessages);
      localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages));
    } catch (error) {
      console.error('Image error:', error);
      const errorMessage = { role: 'assistant', content: 'Ошибка распознавания фото.', isError: true };
      const finalMessages = [...newMessages, errorMessage];
      setMessages(finalMessages);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFileSelect = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    if (file.type === 'application/pdf') {
      await processPdf(file);
    } else if (file.type.startsWith('image/')) {
      await processImage(file);
    } else {
      alert('Пожалуйста, выберите изображение или PDF файл.');
    }
    event.target.value = null;
  };

  // === АУДИО ===

  const startRecording = async () => {
    try {
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
        stream.getTracks().forEach(track => track.stop());
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

  // === УРОКИ ===

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
          use_history: useHistory
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

      // 1. Сохраняем уровень на бэкенде
      await fetch(`${backendUrl}/api/set_level`, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ level: selectedLevelStr })
      });

      // 2. Если уровень "0" (Абсолютный новичок)
      if (selectedLevelStr === "0") {
        // Берем контекст из последнего реального перевода (перед карточкой оценки)
        const userMsg = messages[msgIdx - 2];
        const aiMsg = messages[msgIdx - 1];

        // Превращаем карточку оценки в пустой урок (заглушку)
        const newMessages = [...messages];
        newMessages[msgIdx] = { role: 'assistant', content: '', isLesson: true };
        setMessages(newMessages);

        // Отправляем запрос на генерацию урока
        const lessonResponse = await fetch(`${backendUrl}/api/lesson`, {
          method: 'POST',
          headers: headers,
          body: JSON.stringify({
            user_text: userMsg?.content || "",
            ai_text: aiMsg?.content || "",
            use_history: false
          })
        });

        if (!lessonResponse.ok) throw new Error('Lesson generation failed');
        const data = await lessonResponse.json();

        // Заменяем заглушку на реальный урок
        const finalMessages = [...newMessages];
        finalMessages[msgIdx] = {
          role: 'assistant',
          content: data.lesson || "Не удалось создать урок.",
          isLesson: true
        };
        setMessages(finalMessages);
        localStorage.setItem('translator_chat_history', JSON.stringify(finalMessages.filter(m => !m.isError && !m.isAssessment)));

      } else {
        // 3. Обычная логика (для уровней A1 - C2)
        const newMessages = [...messages];
        newMessages[msgIdx] = {
          role: 'assistant',
          content: `🎓Мини-урок! Переведите:\n\n${selectedText}`,
          isLesson: true
        };
        setMessages(newMessages);
        localStorage.setItem('translator_chat_history', JSON.stringify(newMessages.filter(m => !m.isError && !m.isAssessment)));
      }
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

      {/* Кнопка установки PWA */}
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
            const isLastMessage = idx === messages.length - 1;

            if (msg.isAssessment) {
              return (
                <div key={idx} className="message-wrapper assistant">
                  <div className="message assessment-card">
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
                <div className={`message ${msg.role} ${msg.isError ? 'error-message' : ''} ${msg.isLesson ? 'lesson-message' : ''} ${msg.isEvaluation ? 'evaluation-message' : ''}`}>
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

                {/* Тег исходного языка */}
                {msg.role === 'user' && msg.source_language && !msg.evaluation && (
                  <div className="source-language-tag">{msg.source_language}</div>
                )}

                {/* Статус проверки урока под сообщением пользователя */}
                {msg.role === 'user' && msg.evalData && (
                  <div className="source-language-tag eval-tag">
                    {msg.showExplainLink && (
                      <button className="ideal-translation-link" onClick={() => toggleExplanation(idx)}>
                        идеальный перевод
                      </button>
                    )}
                    <span>{msg.evalData.grade}</span>
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
            <p>Пришли то, что тебе не понятно, или скажи, какой язык хочешь изучать.</p>
          </div>
        )
      )}

      <div className="input-area">
        {/* Кнопка скрепки (системное меню) */}
        <button className="action-btn" aria-label="Прикрепить файл" onClick={() => fileInputRef.current.click()}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
          </svg>
        </button>

        {/* Единый скрытый инпут для Фото и PDF */}
        <input
          type="file"
          accept="image/*,application/pdf"
          ref={fileInputRef}
          style={{ display: 'none' }}
          onChange={handleFileSelect}
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

        <div className="send-wrapper">
          {/* Обычная кнопка отправки (синяя) */}
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

          {/* Кнопка Мини-урока (появляется поверх, если поле ввода пустое) */}
          {!input.trim() && !isLoading && messages.length > 0 && messages[messages.length - 1].role === 'assistant' && !messages[messages.length - 1].isError && !messages[messages.length - 1].isLesson && !messages[messages.length - 1].hideLesson && (
            <button
              className="send-btn mini-lesson-overlay"
              onClick={() => generateLesson(messages.length - 1)}
              aria-label="Мини-урок"
            >
              {/* Белая SVG-иконка graduation cap */}
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 10v6M2 10l10-5 10 5-10 5z"/>
                <path d="M6 12v5c3 3 9 3 12 0v-5"/>
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;