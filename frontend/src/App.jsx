import { useState, useRef, useEffect, useLayoutEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './App.css';

// IndexedDB Helper
const DB_NAME = 'linguachat';
const STORE_NAME = 'images';
function openDB() {
  return new Promise((resolve) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME);
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = () => resolve(null);
  });
}
async function idbGet(key) {
  const db = await openDB();
  if (!db) return null;
  return new Promise((resolve) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).get(key);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => resolve(null);
  });
}
async function idbSet(key, val) {
  const db = await openDB();
  if (!db) return;
  return new Promise((resolve) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(val, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => resolve();
  });
}

function loadCachedMessages() {
  try {
    const cached = localStorage.getItem('translator_chat_history');
    if (cached) {
      const parsed = JSON.parse(cached);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch (e) { console.error("Cache load error", e); }
  return [];
}

function Typewriter() {
  const phrases = ["Отправьте текст или фото для перевода", "Или ответьте какой у вас уровень испанского?"];
  const [text, setText] = useState("");
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [speed, setSpeed] = useState(100);

  useEffect(() => {
    const currentPhrase = phrases[phraseIndex];
    let timer;
    if (!isDeleting && text === currentPhrase) {
      timer = setTimeout(() => setIsDeleting(true), 2000);
    } else if (isDeleting && text === "") {
      setIsDeleting(false);
      setPhraseIndex((prev) => (prev + 1) % phrases.length);
    } else {
      timer = setTimeout(() => {
        setText(prev => {
          if (isDeleting) return currentPhrase.substring(0, prev.length - 1);
          return currentPhrase.substring(0, prev.length + 1);
        });
      }, isDeleting ? speed / 2 : speed);
    }
    return () => clearTimeout(timer);
  }, [text, isDeleting, phraseIndex]);

  return (
    <div className="empty-state">
      <span className="typewriter">{text}<span className="cursor">|</span></span>
    </div>
  );
}

function App() {
  const [messages, setMessages] = useState(loadCachedMessages);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSyncingHistory, setIsSyncingHistory] = useState(false);
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('translator_session_id') || null);
  const [lightboxSrc, setLightboxSrc] = useState(null);

  const chatContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const isNearBottomRef = useRef(true); // Для smart scroll

  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isAppInstalled, setIsAppInstalled] = useState(false);
  const backendUrl = import.meta.env.VITE_BACKEND_URL || '';

  // Мгновенный скролл вниз при загрузке
  useLayoutEffect(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'auto' });
  }, []);

  // Синхронизация истории
  useEffect(() => {
    if (!sessionId) return;
    const syncHistory = async () => {
      setIsSyncingHistory(true);
      try {
        const response = await fetch(`${backendUrl}/api/history`, { headers: { 'X-Session-Id': sessionId } });
        if (response.ok) {
          const data = await response.json();
          if (data.history) {
            // Загружаем фото из IndexedDB или используем URL
            const historyWithImages = await Promise.all(data.history.map(async (msg) => {
              if (msg.media_url) {
                const localImg = await idbGet(msg.media_url);
                if (localImg) return { ...msg, image: localImg };
              }
              return msg;
            }));
            setMessages(historyWithImages);
            localStorage.setItem('translator_chat_history', JSON.stringify(historyWithImages.map(m => {
              const { image, ...rest } = m; return rest; // Не храним base64 в localStorage
            })));
            // Скролл вниз после синхронизации
            setTimeout(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' }), 50);
          }
        }
      } catch (error) {
        console.error('Ошибка синхронизации истории:', error);
      } finally {
        setIsSyncingHistory(false);
      }
    };
    syncHistory();
  }, []);

  // Сохранение истории без фото
  useEffect(() => {
    if (messages.length > 0) {
      try {
        const cleanMessages = messages.map(m => {
          const { image, ...rest } = m;
          return rest;
        });
        localStorage.setItem('translator_chat_history', JSON.stringify(cleanMessages));
      } catch (e) { console.error("LocalStorage save error", e); }
    }
  }, [messages]);

  // Smart Scroll
  useEffect(() => {
    if (messages.length > 0 && isNearBottomRef.current) {
      const timer = setTimeout(() => {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [messages, isLoading]);

  // Track scroll position
  useEffect(() => {
    const handleScroll = () => {
      const scrollPosition = window.innerHeight + window.scrollY;
      const pageHeight = document.body.offsetHeight;
      isNearBottomRef.current = scrollPosition >= pageHeight - 200; // 200px threshold
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // PWA логика
  useEffect(() => {
    if (window.matchMedia('(display-mode: standalone)').matches) setIsAppInstalled(true);
    const handleBeforeInstallPrompt = (e) => { e.preventDefault(); setDeferredPrompt(e); };
    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    return () => window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
  }, []);

  // Autofocus
  useEffect(() => {
    if (textareaRef.current) textareaRef.current.focus();
  }, []);

  const handleInstallClick = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') setIsAppInstalled(true);
    setDeferredPrompt(null);
  };

  const sendMessage = async (text, file, retryIdx = null) => {
    if (isLoading || (!text && !file)) return;
    setIsLoading(true);

    let imagePreview = null;
    let retryKey = null;
    if (file) {
      if (file.size > 5 * 1024 * 1024) { alert("Файл слишком большой."); setIsLoading(false); return; }
      imagePreview = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.readAsDataURL(file);
      });
    }

    // Если это retry, удаляем старое сообщение об ошибке
    let newMessages = [...messages];
    if (retryIdx !== null) {
      newMessages.splice(retryIdx, 1);
      setMessages(newMessages);
    }

    const userMessage = { role: 'user', content: text || '', image: imagePreview, retryText: text, retryImage: imagePreview };
    newMessages = [...newMessages, userMessage];
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

      if (data.media_url) {
        // Кэшируем в IndexedDB
        await idbSet(data.media_url, imagePreview);
        newMessages[newMessages.length - 1] = { ...newMessages[newMessages.length - 1], image: imagePreview, media_url: data.media_url, retryImage: null };
      }

      setMessages([...newMessages, { role: 'assistant', content: data.translation }]);
    } catch (error) {
      console.error('Ошибка отправки:', error);
      setMessages([...newMessages, { role: 'assistant', content: 'Не удалось отправить. отправить ещё раз', isError: true, retryText: text, retryImage: imagePreview }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    isNearBottomRef.current = true; // Force scroll down on new send
    await sendMessage(input, null);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading) handleSend();
    }
  };

  const handleRetry = async (idx) => {
    const msg = messages[idx];
    if (!msg) return;

    // Восстанавливаем файл из base64
    let file = null;
    if (msg.retryImage) {
      const byteString = atob(msg.retryImage.split(',')[1]);
      const mimeString = msg.retryImage.split(',')[0].split(':')[1].split(';')[0];
      const ab = new ArrayBuffer(byteString.length);
      const ia = new Uint8Array(ab);
      for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
      file = new Blob([ab], {type: mimeString});
    }
    isNearBottomRef.current = true;
    await sendMessage(msg.retryText || null, file, idx);
  };

    return (
    <div className={`app-container ${messages.length === 0 ? 'empty-state-app' : 'chat-active-app'}`}>

      {/* Тень под системным Status Bar (только если есть сообщения) */}
      {messages.length > 0 && <div className="status-bar-shadow"></div>}

      {/* Кнопка установки PWA вынесена отдельно */}
      {!isAppInstalled && deferredPrompt && (
        <button className="login-btn" onClick={handleInstallClick}>
          <span>Установить</span>
        </button>
      )}

      {isSyncingHistory && (
        <div className="sync-loader">
          <span></span><span></span><span></span>
        </div>
      )}

      {messages.length > 0 ? (
        <div className="chat-container" ref={chatContainerRef}>
          {messages.map((msg, idx) => {
            const rotations = ['-2deg', '1.5deg', '-1deg', '2deg'];
            const rotation = rotations[idx % 4];
            const imageSrc = msg.image || msg.media_url;

            return (
              <div key={idx} className={`message-wrapper ${msg.role}`}>
                {imageSrc && (
                  <div className="polaroid" style={{ transform: `rotate(${rotation})` }} onClick={() => setLightboxSrc(imageSrc)}>
                    <img src={imageSrc} alt="Upload" />
                  </div>
                )}
                {msg.content && (
                  <div className={`message ${msg.role} ${msg.isError ? 'error-message' : ''}`}>
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                      {msg.isError && (
                        <span className="retry-link" onClick={() => handleRetry(idx)}>отправить ещё раз</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {isLoading && (
            <div className="message-wrapper assistant">
              <div className="message assistant typing"><span></span><span></span><span></span></div>
            </div>
          )}
        </div>
      ) : (
        !isLoading && !isSyncingHistory && <Typewriter />
      )}

      {lightboxSrc && (
        <div className="lightbox" onClick={() => setLightboxSrc(null)}>
          <img src={lightboxSrc} alt="Fullscreen" />
        </div>
      )}

      <div className="input-area">
        <input
          type="file"
          accept="image/*"
          ref={fileInputRef}
          style={{ display: 'none' }}
          onChange={(e) => { const file = e.target.files[0]; if (file) { isNearBottomRef.current = true; sendMessage(null, file); } e.target.value = null; }}
        />
        <button className="action-btn" onClick={() => fileInputRef.current.click()} disabled={isLoading} aria-label="Прикрепить фото">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>
        </button>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Сообщение..."
          rows={1}
        />
        <div className="send-wrapper">
          <button onClick={handleSend} disabled={!input.trim() || isLoading} className="send-btn" aria-label="Отправить">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;