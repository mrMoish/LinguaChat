import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './App.css';
import { searchLanguages, popularLanguages } from './languages';

const LONG_PRESS_MS = 280;
const HINT_STEP_MS = 1000;

function hasForeignText(text) {
  if (!text) return false;
  return /[^\u0000-\u007F\u0400-\u04FF\s.,!?;:'"()\-–—…«»0-9]/.test(text) || /[A-Za-z]/.test(text);
}

function pickVoice(voices, locale) {
  if (!voices || voices.length === 0) return null;
  const exact = voices.find(v => v.lang === locale);
  if (exact) return exact;
  const base = (locale || '').split('-')[0];
  const baseMatch = voices.find(v => v.lang && v.lang.split('-')[0] === base);
  if (baseMatch) return baseMatch;
  return null;
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isInitializing, setIsInitializing] = useState(true);
  const [sessionId, setSessionId] = useState(null);

  const [targetLangCode, setTargetLangCode] = useState(null);
  const [languageLocale, setLanguageLocale] = useState(null);
  const [pendingQuestion, setPendingQuestion] = useState('');

  const [hintStates, setHintStates] = useState({});
  const hintTimersRef = useRef({});

  const chatContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const voicesRef = useRef([]);

  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isAppInstalled, setIsAppInstalled] = useState(false);

  const [isRecording, setIsRecording] = useState(false);
  const [voiceSessionOpen, setVoiceSessionOpen] = useState(false);
  const [voiceSessionStatus, setVoiceSessionStatus] = useState('listening');
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const recognitionRef = useRef(null);
  const pressTimerRef = useRef(null);
  const pressStartedLongRef = useRef(false);
  const voiceSessionActiveRef = useRef(false);

  const backendUrl = import.meta.env.VITE_BACKEND_URL || '';

  useEffect(() => {
    const loadVoices = () => { voicesRef.current = window.speechSynthesis.getVoices(); };
    loadVoices();
    if ('speechSynthesis' in window) {
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }, []);

  useEffect(() => {
    const initChat = async () => {
      let currentSessionId = localStorage.getItem('translator_session_id');
      try {
        const headers = {};
        if (currentSessionId) headers['X-Session-Id'] = currentSessionId;
        const response = await fetch(`${backendUrl}/api/history`, { headers });
        if (response.ok) {
          const data = await response.json();
          localStorage.setItem('translator_session_id', data.session_id);
          setSessionId(data.session_id);

          if (data.settings) {
            setTargetLangCode(data.settings.target_language_code);
            setLanguageLocale(data.settings.language_locale);
          }
          setMessages(data.history || []);

          const lastAssistant = [...(data.history || [])].reverse().find(m => m.role === 'assistant');
          if (lastAssistant) {
            const parts = lastAssistant.content.split('\n\n');
            setPendingQuestion(parts[parts.length - 1] || lastAssistant.content);
          }
        }
      } catch (error) {
        console.error('Ошибка загрузки истории:', error);
      } finally {
        setIsInitializing(false);
      }
    };
    initChat();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (messages.length > 0) {
      const timer = setTimeout(() => {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
      }, 100);
      return () => clearTimeout(timer);
    }
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

  const [languageQuery, setLanguageQuery] = useState('');

  const selectLanguage = async (lang) => {
    setIsLoading(true);
    try {
      const response = await fetch(`${backendUrl}/api/select_language`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(sessionId ? { 'X-Session-Id': sessionId } : {}) },
        body: JSON.stringify({ code: lang.code, locale: lang.locale, name: lang.name })
      });
      const data = await response.json();
      localStorage.setItem('translator_session_id', data.session_id);
      setSessionId(data.session_id);
      setTargetLangCode(data.target_language_code);
      setLanguageLocale(data.language_locale);
      setPendingQuestion(data.question);
      setMessages([{ role: 'assistant', content: data.question }]);
      setLanguageQuery('');
    } catch (error) {
      console.error('Ошибка выбора языка:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const applyMessageResponse = (data, baseMessages) => {
    const finalMessages = [...baseMessages];
    const lastIdx = finalMessages.length - 1;
    if (lastIdx >= 0 && finalMessages[lastIdx].role === 'user' && data.user_feedback) {
      finalMessages[lastIdx] = { ...finalMessages[lastIdx], feedback: data.user_feedback };
    }

    if (data.mode === 'isolated') {
      finalMessages.push({
        role: 'assistant',
        content: data.translation_package?.target_text || 'Перевод',
        feedback: data.translation_package
      });
    } else {
      const content = data.reaction ? `${data.reaction}\n\n${data.next_question}`.trim() : data.next_question;
      finalMessages.push({ role: 'assistant', content });
      setPendingQuestion(data.next_question);
    }

    setMessages(finalMessages);
  };

  const sendMessage = async (text) => {
    if (!text.trim() || isLoading || !targetLangCode) return;
    setIsLoading(true);
    const userMessage = { role: 'user', content: text };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);

    try {
      const response = await fetch(`${backendUrl}/api/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(sessionId ? { 'X-Session-Id': sessionId } : {}) },
        body: JSON.stringify({ message: text, current_question: pendingQuestion })
      });
      if (!response.ok) throw new Error('Network error');
      const data = await response.json();
      applyMessageResponse(data, newMessages);
      return data;
    } catch (error) {
      console.error('Ошибка отправки:', error);
      setMessages([...newMessages, { role: 'assistant', content: 'Не получилось отправить сообщение. Попробуйте позже.', isError: true }]);
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

  const handleReplaceQuestion = async () => {
    if (isLoading || !targetLangCode) return;
    setIsLoading(true);
    try {
      const response = await fetch(`${backendUrl}/api/replace_question`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(sessionId ? { 'X-Session-Id': sessionId } : {}) },
        body: JSON.stringify({ current_question: pendingQuestion })
      });
      const data = await response.json();
      setPendingQuestion(data.question);
      setMessages(prev => {
        const arr = [...prev];
        const lastIdx = arr.length - 1;
        if (lastIdx >= 0 && arr[lastIdx].role === 'assistant') {
          arr[lastIdx] = { ...arr[lastIdx], content: data.question };
        }
        return arr;
      });
    } catch (error) {
      console.error('Ошибка замены вопроса:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && targetLangCode) handleSend();
    }
  };

  const runHintCycle = async (idx, text) => {
    let state = hintStates[idx];
    if (!state || !state.data) {
      setHintStates(prev => ({ ...prev, [idx]: { step: 0, data: null, loading: true } }));
      try {
        const response = await fetch(`${backendUrl}/api/hint`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(sessionId ? { 'X-Session-Id': sessionId } : {}) },
          body: JSON.stringify({ text })
        });
        const data = await response.json();
        state = { step: 0, data, loading: false };
        setHintStates(prev => ({ ...prev, [idx]: state }));
      } catch (error) {
        console.error('Ошибка подсказки:', error);
        setHintStates(prev => ({ ...prev, [idx]: { step: 0, data: null, loading: false } }));
        return;
      }
    }

    if (hintTimersRef.current[idx]) clearInterval(hintTimersRef.current[idx]);
    let step = 0;
    setHintStates(prev => ({ ...prev, [idx]: { ...prev[idx], step: 0 } }));
    hintTimersRef.current[idx] = setInterval(() => {
      step += 1;
      if (step > 4) {
        clearInterval(hintTimersRef.current[idx]);
        delete hintTimersRef.current[idx];
        setHintStates(prev => ({ ...prev, [idx]: { ...prev[idx], step: 0 } }));
        return;
      }
      setHintStates(prev => ({ ...prev, [idx]: { ...prev[idx], step } }));
    }, HINT_STEP_MS);
  };

  const getHintDisplayText = (idx, originalText) => {
    const state = hintStates[idx];
    if (!state || !state.data) return originalText;
    const { step, data } = state;
    switch (step) {
      case 1: return data.pronunciation_hint || originalText;
      case 2: return data.literal_translation || originalText;
      case 3: return data.meaning_translation || originalText;
      default: return originalText;
    }
  };

  const speakMessage = (text) => {
    if (!text || !('speechSynthesis' in window)) {
      if (!('speechSynthesis' in window)) alert('Озвучка не поддерживается в этом браузере.');
      return Promise.resolve();
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = pickVoice(voicesRef.current.length ? voicesRef.current : window.speechSynthesis.getVoices(), languageLocale);
    if (voice) {
      utterance.voice = voice;
      utterance.lang = voice.lang;
    } else if (languageLocale) {
      utterance.lang = languageLocale;
    }
    return new Promise((resolve) => {
      utterance.onend = resolve;
      utterance.onerror = resolve;
      window.speechSynthesis.speak(utterance);
    });
  };

  const processPdf = async (file) => {
    setIsLoading(true);
    const userMessage = { role: 'user', content: `📄 Загружен файл: ${file.name}` };
    const aiMessage = { role: 'assistant', content: '' };
    setMessages(prev => [...prev, userMessage, aiMessage]);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const headers = {};
      if (sessionId) headers['X-Session-Id'] = sessionId;
      const response = await fetch(`${backendUrl}/api/upload_pdf`, { method: 'POST', headers, body: formData });
      if (!response.ok) throw new Error('Upload failed');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunkText = decoder.decode(value, { stream: true });
        setMessages(prev => {
          const arr = [...prev];
          arr[arr.length - 1] = { ...arr[arr.length - 1], content: arr[arr.length - 1].content + chunkText };
          return arr;
        });
      }
    } catch (error) {
      console.error('Ошибка файла:', error);
      setMessages(prev => {
        const arr = [...prev];
        arr[arr.length - 1] = { ...arr[arr.length - 1], content: 'Ошибка при обработке файла.', isError: true };
        return arr;
      });
    } finally {
      setIsLoading(false);
    }
  };

  const processImage = async (file) => {
    setIsLoading(true);
    const userMessage = { role: 'user', content: '📷 Фото для перевода' };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const headers = {};
      if (sessionId) headers['X-Session-Id'] = sessionId;
      const response = await fetch(`${backendUrl}/api/image_translate`, { method: 'POST', headers, body: formData });
      if (!response.ok) throw new Error('Image translation failed');
      const data = await response.json();
      setMessages([...newMessages, { role: 'assistant', content: data.reply }]);
    } catch (error) {
      console.error('Ошибка фото:', error);
      setMessages([...newMessages, { role: 'assistant', content: 'Ошибка распознавания фото.', isError: true }]);
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

  const startAudioRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };

      let finalTranscript = '';
      const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
      let recognition = null;
      if (SpeechRecognitionCtor) {
        recognition = new SpeechRecognitionCtor();
        recognition.lang = languageLocale || 'ru-RU';
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.onresult = (event) => {
          for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript + ' ';
          }
        };
        recognition.start();
        recognitionRef.current = recognition;
      }

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        if (recognitionRef.current) {
          try { recognitionRef.current.stop(); } catch (e) {}
        }
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        const audioUrl = URL.createObjectURL(audioBlob);
        const transcript = finalTranscript.trim();

        if (!transcript) {
          setMessages(prev => [...prev, { role: 'assistant', content: 'Не удалось распознать голосовое сообщение. Попробуй ещё раз или напиши текстом.', isError: true }]);
          return;
        }
        setMessages(prev => [...prev, { role: 'user', content: transcript, isVoice: true, audioUrl }]);
        await sendMessage(transcript);
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error('Ошибка доступа к микрофону:', err);
      alert('Нет доступа к микрофону. Разрешите доступ в настройках браузера.');
    }
  };

  const stopAudioRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
  };

  const handleMicPointerDown = () => {
    pressStartedLongRef.current = false;
    pressTimerRef.current = setTimeout(() => {
      pressStartedLongRef.current = true;
      startAudioRecording();
    }, LONG_PRESS_MS);
  };

  const handleMicPointerUp = () => {
    if (pressTimerRef.current) {
      clearTimeout(pressTimerRef.current);
      pressTimerRef.current = null;
    }
    if (pressStartedLongRef.current) {
      stopAudioRecording();
    } else {
      openVoiceSession();
    }
  };

  const openVoiceSession = () => {
    setVoiceSessionOpen(true);
    voiceSessionActiveRef.current = true;
    voiceSessionTurn();
  };

  const closeVoiceSession = () => {
    voiceSessionActiveRef.current = false;
    setVoiceSessionOpen(false);
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch (e) {}
    }
    window.speechSynthesis.cancel();
  };

  const voiceSessionTurn = () => {
    if (!voiceSessionActiveRef.current) return;
    setVoiceSessionStatus('listening');
    const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) {
      alert('Голосовой режим не поддерживается в этом браузере.');
      closeVoiceSession();
      return;
    }
    const recognition = new SpeechRecognitionCtor();
    recognition.lang = languageLocale || 'ru-RU';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognitionRef.current = recognition;

    recognition.onresult = async (event) => {
      if (!voiceSessionActiveRef.current) return;
      const transcript = event.results[0][0].transcript;
      setVoiceSessionStatus('thinking');
      const data = await sendMessage(transcript);
      if (!voiceSessionActiveRef.current) return;
      setVoiceSessionStatus('speaking');
      const spokenText = data?.mode === 'isolated'
        ? (data.translation_package?.target_text || '')
        : `${data?.reaction || ''} ${data?.next_question || ''}`.trim();
      await speakMessage(spokenText);
      voiceSessionTurn();
    };
    recognition.onerror = () => {
      if (voiceSessionActiveRef.current) voiceSessionTurn();
    };
    recognition.start();
  };

  const renderMessageContent = (msg, idx) => {
    if (msg.feedback && msg.feedback.type === 'translation_package') {
      const tp = msg.feedback;
      return (
        <div className="translation-card">
          <div className="translation-card-main">{tp.target_text}</div>
          <div className="translation-card-sub">{tp.pronunciation_hint}</div>
          <div className="translation-card-sub">{tp.literal_translation}</div>
          <div className="translation-card-sub">{tp.meaning_translation}</div>
          <button className="translation-copy-btn" onClick={() => navigator.clipboard?.writeText(tp.target_text)}>
            Копировать
          </button>
        </div>
      );
    }
    const displayText = getHintDisplayText(idx, msg.content);
    return (
      <div className="markdown-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayText || ''}</ReactMarkdown>
      </div>
    );
  };

  const showLanguagePicker = !isInitializing && !targetLangCode;
  const filteredLanguages = languageQuery.trim() ? searchLanguages(languageQuery) : [];
  const popular = popularLanguages();

  return (
    <div className={`app-container ${messages.length === 0 && !showLanguagePicker ? 'empty-state-app' : 'chat-active-app'}`}>
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

      {showLanguagePicker ? (
        <div className="empty-state language-picker">
          <p>Какой язык хочешь изучать?</p>
          {filteredLanguages.length > 0 ? (
            <div className="language-grid">
              {filteredLanguages.map(lang => (
                <button key={lang.code} className="language-btn" onClick={() => selectLanguage(lang)} disabled={isLoading}>
                  {lang.name}
                </button>
              ))}
            </div>
          ) : languageQuery.trim() ? (
            <p className="language-empty">Ничего не найдено</p>
          ) : (
            <div className="language-grid">
              {popular.map(lang => (
                <button key={lang.code} className="language-btn" onClick={() => selectLanguage(lang)} disabled={isLoading}>
                  {lang.name}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : messages.length > 0 ? (
        <div className="chat-container" ref={chatContainerRef}>
          {messages.map((msg, idx) => {
            const isTranslationCard = msg.feedback && msg.feedback.type === 'translation_package';
            return (
              <div key={idx} className={`message-wrapper ${msg.role}`}>
                <div className={`message ${msg.role} ${msg.isError ? 'error-message' : ''}`}>
                  {msg.isVoice && <audio controls src={msg.audioUrl} className="voice-message-player" />}
                  {renderMessageContent(msg, idx)}
                </div>

                {!isTranslationCard && hasForeignText(msg.content) && !msg.isError && (
                  <div className="hint-controls">
                    <button className="tts-btn" onClick={() => speakMessage(msg.content)} aria-label="Воспроизвести">🔊</button>
                    <button className="hint-btn" onClick={() => runHintCycle(idx, msg.content)} aria-label="Подсказка">💡</button>
                  </div>
                )}

                {msg.role === 'user' && msg.feedback && msg.feedback.type === 'correction' && (
                  <div className="source-language-tag eval-tag">{msg.feedback.correction}</div>
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
      ) : null}

      {!showLanguagePicker && (
        <div className="input-area">
          <button className="action-btn" aria-label="Прикрепить файл" onClick={() => fileInputRef.current.click()}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
            </svg>
          </button>
          <input type="file" accept="image/*,application/pdf" ref={fileInputRef} style={{ display: 'none' }} onChange={handleFileSelect} />

          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Введите текст..."
            rows={1}
          />

          <button
            className={`action-btn mic-btn ${isRecording ? 'recording' : ''}`}
            onPointerDown={handleMicPointerDown}
            onPointerUp={handleMicPointerUp}
            onPointerLeave={() => { if (pressTimerRef.current) { clearTimeout(pressTimerRef.current); pressTimerRef.current = null; } }}
            aria-label="Микрофон"
          >
            {isRecording ? <span className="rec-dot"></span> : (
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                <line x1="12" y1="19" x2="12" y2="23"></line>
                <line x1="8" y1="23" x2="16" y2="23"></line>
              </svg>
            )}
          </button>

          <div className="send-wrapper">
            {input.trim() ? (
              <button onClick={handleSend} disabled={isLoading} className="send-btn" aria-label="Отправить">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              </button>
            ) : (
              <button onClick={handleReplaceQuestion} disabled={isLoading || !targetLangCode} className="replace-question-btn" aria-label="Заменить вопрос">
                🔄 Заменить вопрос
              </button>
            )}
          </div>
        </div>
      )}

      {voiceSessionOpen && (
        <div className="voice-session-overlay">
          <div className={`voice-session-circle ${voiceSessionStatus}`}></div>
          <div className="voice-session-status">
            {voiceSessionStatus === 'listening' && 'Слушаю...'}
            {voiceSessionStatus === 'thinking' && 'Думаю...'}
            {voiceSessionStatus === 'speaking' && 'Говорю...'}
          </div>
          <button className="voice-session-close" onClick={closeVoiceSession}>Завершить</button>
        </div>
      )}
    </div>
  );
}

export default App;
