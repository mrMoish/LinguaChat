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
  const phrases = ["Отправьте текст или фото для перевода", "Или какой у вас уровень китайского?"];
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
        setText(prev => isDeleting ? currentPhrase.substring(0, prev.length - 1) : currentPhrase.substring(0, prev.length + 1));
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

const PAGE_SIZE = 20;

function App() {
  const [allMessages, setAllMessages] = useState(loadCachedMessages);
  const [visibleMessages, setVisibleMessages] = useState([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSyncingHistory, setIsSyncingHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [sessionId, setSessionId] = useState(() => localStorage.getItem('translator_session_id') || null);
  const [lightboxSrc, setLightboxSrc] = useState(null);

  // Состояния для клавиатуры и viewport
  const [viewportHeight, setViewportHeight] = useState(window.innerHeight);
  const [bottomOffset, setBottomOffset] = useState(0);

  const chatContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const isNearBottomRef = useRef(true);

  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isAppInstalled, setIsAppInstalled] = useState(false);
  const backendUrl = import.meta.env.VITE_BACKEND_URL || '';

  useEffect(() => {
    const startIdx = Math.max(0, allMessages.length - currentPage * PAGE_SIZE);
    setVisibleMessages(allMessages.slice(startIdx));
    setHasMore(startIdx > 0);
  }, [allMessages, currentPage]);

  useLayoutEffect(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'auto' });
  }, []);

  // Обработка visualViewport для клавиатуры
  useEffect(() => {
    const onResize = () => {
      const offset = window.innerHeight - visualViewport.height - visualViewport.offsetTop;
      setBottomOffset(offset > 0 ? offset : 0);
      setViewportHeight(visualViewport.height);
    };
    window.visualViewport.addEventListener('resize', onResize);
    onResize();
    return () => window.visualViewport.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    const syncHistory = async () => {
      setIsSyncingHistory(true);
      try {
        const response = await fetch(`${backendUrl}/api/history`, { headers: { 'X-Session-Id': sessionId } });
        if (response.ok) {
          const data = await response.json();
          if (data.history) {
            const historyWithImages = await Promise.all(data.history.map(async (msg) => {
              if (msg.media_url) {
                const localImg = await idbGet(msg.media_url);
                if (localImg) return { ...msg, image: localImg };
              }
              return msg;
            }));
            setAllMessages(historyWithImages);
            setCurrentPage(1);
            localStorage.setItem('translator_chat_history', JSON.stringify(historyWithImages.map(m => {
              const { image, ...rest } = m; return rest;
            })));
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

  useEffect(() => {
    if (allMessages.length > 0) {
      try {
        const cleanMessages = allMessages.map(m => {
          const { image, ...rest } = m;
          return rest;
        });
        localStorage.setItem('translator_chat_history', JSON.stringify(cleanMessages));
      } catch (e) { console.error("LocalStorage save error", e); }
    }
  }, [allMessages]);

  useEffect(() => {
    const handleScroll = () => {
      const scrollPosition = window.innerHeight + window.scrollY;
      const pageHeight = document.body.offsetHeight;

      if (scrollPosition >= pageHeight - 100) {
        isNearBottomRef.current = true;
        setShowScrollBtn(false);
      } else {
        isNearBottomRef.current = false;
      }

      if (window.scrollY < 200 && hasMore && !isLoadingMore) {
        setIsLoadingMore(true);
        const oldScrollHeight = document.body.scrollHeight;

        const nextPage = currentPage + 1;
        const startIdx = Math.max(0, allMessages.length - nextPage * PAGE_SIZE);
        const newVisible = allMessages.slice(startIdx);

        setVisibleMessages(newVisible);
        setHasMore(startIdx > 0);
        setCurrentPage(nextPage);

        requestAnimationFrame(() => {
          const newScrollHeight = document.body.scrollHeight;
          window.scrollTo({ top: newScrollHeight - oldScrollHeight, behavior: 'auto' });
          setIsLoadingMore(false);
        });
      }
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, [hasMore, isLoadingMore, currentPage, allMessages, visibleMessages.length]);

  useEffect(() => {
    if (isNearBottomRef.current && visibleMessages.length > 0) {
      const timer = setTimeout(() => {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [visibleMessages, isLoading, isSyncingHistory]);

  useEffect(() => {
    if (window.matchMedia('(display-mode: standalone)').matches) setIsAppInstalled(true);
    const handleBeforeInstallPrompt = (e) => { e.preventDefault(); setDeferredPrompt(e); };
    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    return () => window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
  }, []);

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
    isNearBottomRef.current = true;

    let imagePreview = null;
    if (file) {
      if (file.size > 5 * 1024 * 1024) { alert("Файл слишком большой."); setIsLoading(false); return; }
      imagePreview = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target.result);
        reader.readAsDataURL(file);
      });
    }

    let newMessages = [...allMessages];
    const userMessage = { role: 'user', content: text || '', image: imagePreview, retryText: text, retryImage: imagePreview };
    newMessages = [...newMessages, userMessage];
    setAllMessages(newMessages);
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
        await idbSet(data.media_url, imagePreview);
        newMessages[newMessages.length - 1] = { ...newMessages[newMessages.length - 1], image: imagePreview, media_url: data.media_url, retryImage: null };
      }

      setAllMessages([...newMessages, { role: 'assistant', content: data.translation }]);
    } catch (error) {
      console.error('Ошибка отправки:', error);
      setAllMessages([...newMessages, { role: 'assistant', content: 'Не удалось отправить. отправить ещё раз', isError: true, retryText: text, retryImage: imagePreview }]);
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

  const handleRetry = async (idx) => {
    const msg = visibleMessages[idx];
    if (!msg) return;
    let file = null;
    if (msg.retryImage) {
      const byteString = atob(msg.retryImage.split(',')[1]);
      const mimeString = msg.retryImage.split(',')[0].split(':')[1].split(';')[0];
      const ab = new ArrayBuffer(byteString.length);
      const ia = new Uint8Array(ab);
      for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);
      file = new Blob([ab], {type: mimeString});
    }
    await sendMessage(msg.retryText || null, file);
  };



  const isEmpty = visibleMessages.length === 0 && !isLoading && !isSyncingHistory;
  const isKeyboardOpen = bottomOffset > 10;

  const InputArea = (
    <div
      className={`input-area ${isEmpty ? 'input-centered' : ''}`}
      style={!isEmpty ? {
        bottom: `${bottomOffset}px`,
        paddingBottom: isKeyboardOpen ? '10px' : 'calc(20px + env(safe-area-inset-bottom))' // Большой отступ, нет клавы
      } : {}}
    >
      <input
        type="file"
        accept="image/*"
        ref={fileInputRef}
        style={{ display: 'none' }}
        onChange={(e) => { const file = e.target.files[0]; if (file) sendMessage(null, file); e.target.value = null; }}
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
  );

  return (
    <div
      className={`app-container ${isEmpty ? 'empty-state-app' : 'chat-active-app'}`}
      style={isEmpty ? { height: `${viewportHeight}px` } : {}}
    >

      {visibleMessages.length > 0 && <div className="status-bar-shadow"></div>}

      {!isAppInstalled && deferredPrompt && (
        <button className="login-btn" onClick={handleInstallClick}>
          <span>Установить</span>
        </button>
      )}

      {visibleMessages.length > 0 ? (
        <div className="chat-container" ref={chatContainerRef}>
          {isLoadingMore && (
            <div className="message-wrapper assistant">
              <div className="message assistant typing"><span></span><span></span><span></span></div>
            </div>
          )}

          {visibleMessages.map((msg, idx) => {
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

          {isSyncingHistory && (
            <div className="message-wrapper assistant">
              <div className="typing-dots">
                <span></span><span></span><span></span>
              </div>
            </div>
          )}

          {isLoading && (
            <div className="message-wrapper assistant">
              <div className="typing-dots">
                <span></span><span></span><span></span>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="empty-wrapper">
          <Typewriter />
          {InputArea}
        </div>
      )}

      {/* InputArea вынесен из chat-container, чтобы избежать двойных отступов */}
      {!isEmpty && InputArea}


      {lightboxSrc && (
        <div className="lightbox" onClick={() => setLightboxSrc(null)}>
          <img src={lightboxSrc} alt="Fullscreen" />
        </div>
      )}
    </div>
  );
}

export default App;