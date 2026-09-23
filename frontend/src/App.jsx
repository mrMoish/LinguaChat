import { useState, useRef, useEffect, useLayoutEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './App.css';

// ============================================================
// IndexedDB
// ============================================================

const DB_NAME = 'linguachat';
const STORE_NAME = 'images';

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);

    request.onupgradeneeded = () => {
      const db = request.result;

      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function idbGet(key) {
  try {
    const db = await openDB();

    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.get(key);

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  } catch {
    return null;
  }
}

async function idbSet(key, value) {
  try {
    const db = await openDB();

    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      const request = store.put(value, key);

      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
    // Ignore IndexedDB errors.
  }
}

// ============================================================
// Constants
// ============================================================

const PAGE_SIZE = 20;

const WELCOME_MESSAGES = [
  'Отправьте текст или фото для перевода',
  'Или какой у вас уровень китайского?',
];

// ============================================================
// Helpers
// ============================================================

function loadCachedMessages() {
  try {
    const saved = localStorage.getItem('translator_chat_history');

    if (!saved) {
      return [];
    }

    const parsed = JSON.parse(saved);

    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function formatRecordingTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;

  return `${String(minutes).padStart(2, '0')}:${String(
    remainingSeconds
  ).padStart(2, '0')}`;
}

// ============================================================
// Typewriter
// ============================================================

function Typewriter({ texts }) {
  const [index, setIndex] = useState(0);
  const [text, setText] = useState('');
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const currentText = texts[index];

    let timeout;

    if (!deleting && text.length < currentText.length) {
      timeout = setTimeout(() => {
        setText(currentText.slice(0, text.length + 1));
      }, 45);
    } else if (!deleting && text.length === currentText.length) {
      timeout = setTimeout(() => {
        setDeleting(true);
      }, 1800);
    } else if (deleting && text.length > 0) {
      timeout = setTimeout(() => {
        setText(currentText.slice(0, text.length - 1));
      }, 25);
    } else if (deleting && text.length === 0) {
      setDeleting(false);
      setIndex((prev) => (prev + 1) % texts.length);
    }

    return () => clearTimeout(timeout);
  }, [text, deleting, index, texts]);

  return (
    <div className="welcome-message">
      {text}
      <span className="typewriter-cursor">|</span>
    </div>
  );
}

// ============================================================
// SVG Icons
// ============================================================

function SendIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M22 2L11 13" />
      <path d="M22 2L15 22L11 13L2 9L22 2Z" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="23"
      height="23"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <path d="M12 17v5" />
      <path d="M8 22h8" />
    </svg>
  );
}

function AttachmentIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 1 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 6L18 18" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="23"
      height="23"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12l4 4L19 6" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="currentColor"
    >
      <path d="M8 5.5v13L18 12 8 5.5z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="currentColor"
    >
      <rect x="7" y="5" width="4" height="14" rx="1" />
      <rect x="13" y="5" width="4" height="14" rx="1" />
    </svg>
  );
}

// ============================================================
// App
// ============================================================

export default function App() {
  const backendUrl = import.meta.env.VITE_BACKEND_URL || '';

  // ----------------------------------------------------------
  // Messages
  // ----------------------------------------------------------

  const [allMessages, setAllMessages] = useState(loadCachedMessages);
  const [visibleMessages, setVisibleMessages] = useState([]);

  const [currentPage, setCurrentPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  // ----------------------------------------------------------
  // Input
  // ----------------------------------------------------------

  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // ----------------------------------------------------------
  // History
  // ----------------------------------------------------------

  const [isSyncingHistory, setIsSyncingHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const [sessionId, setSessionId] = useState(
    () => localStorage.getItem('translator_session_id') || null
  );

  // ----------------------------------------------------------
  // UI
  // ----------------------------------------------------------

  const [lightboxSrc, setLightboxSrc] = useState(null);

  // ----------------------------------------------------------
  // Audio recording
  // ----------------------------------------------------------

  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const timerRef = useRef(null);

  // ----------------------------------------------------------
  // Audio playback
  // ----------------------------------------------------------

  const [playingAudio, setPlayingAudio] = useState(null);
  const audioRef = useRef(null);

  // ----------------------------------------------------------
  // Refs
  // ----------------------------------------------------------

  const chatContainerRef = useRef(null);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  const isNearBottomRef = useRef(true);

  // ==========================================================
  // Cache messages
  // ==========================================================

  useEffect(() => {
    try {
      localStorage.setItem(
        'translator_chat_history',
        JSON.stringify(allMessages)
      );
    } catch {
      // Ignore storage errors.
    }
  }, [allMessages]);

  // ==========================================================
  // Visible messages / pagination
  // ==========================================================

  useEffect(() => {
    const total = allMessages.length;

    const start = Math.max(0, total - PAGE_SIZE * currentPage);

    setVisibleMessages(allMessages.slice(start));

    setHasMore(start > 0);
  }, [allMessages, currentPage]);

  // ==========================================================
  // Sync history from backend
  // ==========================================================

  useEffect(() => {
    if (!sessionId) {
      return;
    }

    let cancelled = false;

    async function loadHistory() {
      setIsSyncingHistory(true);

      try {
        const response = await fetch(
          `${backendUrl}/api/history?session_id=${encodeURIComponent(
            sessionId
          )}`
        );

        if (!response.ok) {
          throw new Error(`History request failed: ${response.status}`);
        }

        const data = await response.json();

        if (cancelled) {
          return;
        }

        if (Array.isArray(data.messages)) {
          const messages = [];

          for (const message of data.messages) {
            let image = null;

            if (message.message_type === 'image' && message.media_url) {
              image = message.media_url;
            }

            messages.push({
              role: message.role,
              content: message.content || '',
              message_type: message.message_type || 'text',
              media_url: message.media_url || null,
              image,
              audio: null,
            });
          }

          setAllMessages(messages);
          setCurrentPage(1);
        }
      } catch (error) {
        console.error('Failed to load history:', error);
      } finally {
        if (!cancelled) {
          setIsSyncingHistory(false);
        }
      }
    }

    loadHistory();

    return () => {
      cancelled = true;
    };
  }, [sessionId, backendUrl]);

  // ==========================================================
  // Initial scroll to bottom
  // ==========================================================

  useLayoutEffect(() => {
    if (visibleMessages.length === 0) {
      return;
    }

    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: 'auto',
    });
  }, []);

  // ==========================================================
  // Auto scroll
  // ==========================================================

  useEffect(() => {
    if (!isNearBottomRef.current) {
      return;
    }

    if (visibleMessages.length === 0) {
      return;
    }

    const timer = setTimeout(() => {
      window.scrollTo({
        top: document.documentElement.scrollHeight,
        behavior: 'smooth',
      });
    }, 50);

    return () => clearTimeout(timer);
  }, [visibleMessages.length, isLoading]);

  // ==========================================================
  // Scroll handler
  // ==========================================================

  useEffect(() => {
    function handleScroll() {
      const scrollTop = window.scrollY;

      const viewportBottom =
        window.innerHeight + window.scrollY;

      const documentHeight =
        document.documentElement.scrollHeight;

      isNearBottomRef.current =
        documentHeight - viewportBottom < 180;

      if (
        scrollTop < 200 &&
        hasMore &&
        !isLoadingMore
      ) {
        setIsLoadingMore(true);

        setTimeout(() => {
          setCurrentPage((page) => page + 1);
          setIsLoadingMore(false);
        }, 100);
      }
    }

    window.addEventListener('scroll', handleScroll);

    return () => {
      window.removeEventListener('scroll', handleScroll);
    };
  }, [hasMore, isLoadingMore]);

  // ==========================================================
  // Cleanup audio on unmount
  // ==========================================================

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  // ==========================================================
  // Textarea auto resize
  // ==========================================================

  useEffect(() => {
    const textarea = textareaRef.current;

    if (!textarea) {
      return;
    }

    textarea.style.height = 'auto';

    textarea.style.height = `${Math.min(
      textarea.scrollHeight,
      140
    )}px`;
  }, [input]);

  // ==========================================================
  // Audio playback
  // ==========================================================

  function toggleAudio(src, messageId) {
    if (!src) {
      return;
    }

    // Current audio is playing -> stop it.
    if (
      playingAudio === messageId &&
      audioRef.current
    ) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;

      audioRef.current = null;
      setPlayingAudio(null);

      return;
    }

    // Stop another audio.
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current = null;
    }

    const audio = new Audio(src);

    audioRef.current = audio;

    audio.onended = () => {
      setPlayingAudio(null);
      audioRef.current = null;
    };

    audio.onerror = () => {
      setPlayingAudio(null);
      audioRef.current = null;
    };

    setPlayingAudio(messageId);

    audio.play().catch(() => {
      setPlayingAudio(null);
      audioRef.current = null;
    });
  }

  // ==========================================================
  // Recording timer
  // ==========================================================

  function startRecordingTimer() {
    setRecordingTime(0);

    timerRef.current = setInterval(() => {
      setRecordingTime((time) => time + 1);
    }, 1000);
  }

  function stopRecordingTimer() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  // ==========================================================
  // Start recording
  // ==========================================================

  async function startRecording() {
    if (isRecording || isLoading) {
      return;
    }

    try {
      const stream =
        await navigator.mediaDevices.getUserMedia({
          audio: true,
        });

      const recorder = new MediaRecorder(stream);

      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        stream.getTracks().forEach((track) => {
          track.stop();
        });
      };

      recorder.start();

      setIsRecording(true);
      startRecordingTimer();
    } catch (error) {
      console.error('Microphone error:', error);

      alert(
        'Не удалось получить доступ к микрофону.'
      );
    }
  }

  // ==========================================================
  // Cancel recording
  // ==========================================================

  function cancelRecording() {
    const recorder = mediaRecorderRef.current;

    if (recorder && recorder.state !== 'inactive') {
      recorder.ondataavailable = null;
      recorder.stop();
    }

    mediaRecorderRef.current = null;
    audioChunksRef.current = [];

    stopRecordingTimer();

    setRecordingTime(0);
    setIsRecording(false);
  }

  // ==========================================================
  // Finish recording
  // ==========================================================

  function finishRecording() {
    const recorder = mediaRecorderRef.current;

    if (!recorder || recorder.state === 'inactive') {
      return;
    }

    recorder.onstop = () => {
      const stream = recorder.stream;

      stream.getTracks().forEach((track) => {
        track.stop();
      });

      const blob = new Blob(
        audioChunksRef.current,
        {
          type: recorder.mimeType || 'audio/webm',
        }
      );

      mediaRecorderRef.current = null;
      audioChunksRef.current = [];

      stopRecordingTimer();

      setRecordingTime(0);
      setIsRecording(false);

      if (blob.size > 0) {
        sendMessage('', blob);
      }
    };

    recorder.stop();
  }

  // ==========================================================
  // Send message
  // ==========================================================

  async function sendMessage(text = input, file = null) {
    if (isLoading) {
      return;
    }

    const trimmedText = text.trim();

    if (!trimmedText && !file) {
      return;
    }

    isNearBottomRef.current = true;

    let messageType = 'text';

    if (file) {
      if (file.type.startsWith('image/')) {
        messageType = 'image';
      } else if (file.type.startsWith('audio/')) {
        messageType = 'audio';
      }
    }

    const localAudioUrl =
      messageType === 'audio'
        ? URL.createObjectURL(file)
        : null;

    const optimisticMessage = {
      role: 'user',
      content: trimmedText,
      message_type: messageType,
      image: null,
      audio: localAudioUrl,
      media_url: null,
    };

    setAllMessages((messages) => [
      ...messages,
      optimisticMessage,
    ]);

    setCurrentPage(1);

    setInput('');
    setIsLoading(true);

    try {
      const formData = new FormData();

      if (trimmedText) {
        formData.append('text', trimmedText);
      }

      if (file) {
        formData.append('file', file);
      }

      if (sessionId) {
        formData.append('session_id', sessionId);
      }

      const response = await fetch(
        `${backendUrl}/api/message`,
        {
          method: 'POST',
          body: formData,
        }
      );

      if (!response.ok) {
        const errorText = await response.text();

        throw new Error(
          errorText ||
            `Request failed: ${response.status}`
        );
      }

      const data = await response.json();

      // ------------------------------------------------------
      // Save session ID
      // ------------------------------------------------------

      if (data.session_id) {
        localStorage.setItem(
          'translator_session_id',
          data.session_id
        );

        setSessionId(data.session_id);
      }

      // ------------------------------------------------------
      // Update optimistic user message
      // ------------------------------------------------------

      setAllMessages((messages) => {
        const updated = [...messages];

        const lastUserIndex =
          [...updated]
            .map((message, index) => ({
              message,
              index,
            }))
            .reverse()
            .find(
              ({ message }) =>
                message.role === 'user'
            )?.index;

        if (
          lastUserIndex !== undefined
        ) {
          const current =
            updated[lastUserIndex];

          if (messageType === 'audio') {
            updated[lastUserIndex] = {
              ...current,
              content:
                data.transcription || '',
              media_url:
                data.media_url || null,
              audio:
                data.media_url ||
                current.audio ||
                null,
              message_type: 'audio',
            };
          } else if (
            messageType === 'image'
          ) {
            updated[lastUserIndex] = {
              ...current,
              media_url:
                data.media_url || null,
              image:
                data.media_url ||
                current.image ||
                null,
              message_type: 'image',
            };
          }
        }

        return updated;
      });

      // ------------------------------------------------------
      // Add assistant response
      // ------------------------------------------------------

      if (data.translation) {
        setAllMessages((messages) => [
          ...messages,
          {
            role: 'assistant',
            content: data.translation,
            message_type: 'text',
            image: null,
            audio: null,
            media_url: null,
          },
        ]);
      }

      // ------------------------------------------------------
      // Cleanup local audio URL
      // ------------------------------------------------------

      if (localAudioUrl) {
        setTimeout(() => {
          URL.revokeObjectURL(localAudioUrl);
        }, 5000);
      }
    } catch (error) {
      console.error('Send message error:', error);

      setAllMessages((messages) => [
        ...messages,
        {
          role: 'assistant',
          content:
            'Не удалось отправить сообщение. Попробуйте ещё раз.',
          message_type: 'error',
          image: null,
          audio: null,
          media_url: null,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }

  // ==========================================================
  // File selection
  // ==========================================================

  function handleFileSelect(event) {
    const file = event.target.files?.[0];

    event.target.value = '';

    if (!file) {
      return;
    }

    const maxSize = 5 * 1024 * 1024;

    if (file.size > maxSize) {
      alert('Файл слишком большой. Максимальный размер — 5 МБ.');
      return;
    }

    sendMessage('', file);
  }

  // ==========================================================
  // Retry
  // ==========================================================

  async function handleRetry(message) {
    if (message.message_type === 'image') {
      let blob = null;

      if (message.media_url) {
        try {
          const response = await fetch(
            message.media_url
          );

          blob = await response.blob();
        } catch (error) {
          console.error(
            'Failed to download image:',
            error
          );
        }
      }

      if (blob) {
        await sendMessage(
          message.content || '',
          blob
        );
      }
    }
  }

  // ==========================================================
  // Keyboard
  // ==========================================================

  function handleKeyDown(event) {
    if (
      event.key === 'Enter' &&
      !event.shiftKey
    ) {
      event.preventDefault();

      if (input.trim()) {
        sendMessage();
      }
    }
  }

  // ==========================================================
  // Render
  // ==========================================================

  return (
    <div className="app">
      <main
        ref={chatContainerRef}
        className="chat-container"
      >
        {visibleMessages.length === 0 && (
          <Typewriter texts={WELCOME_MESSAGES} />
        )}

        {isLoadingMore && (
          <div className="loading-more">
            Загрузка...
          </div>
        )}

        {visibleMessages.map((msg, index) => {
          const imageSrc =
            msg.image ||
            (
              msg.message_type === 'image'
                ? msg.media_url
                : null
            );

          const audioSrc =
            msg.audio ||
            (
              msg.message_type === 'audio'
                ? msg.media_url
                : null
            );

          const audioId =
            `${index}-${msg.role}-${msg.message_type}`;

          return (
            <div
              key={`${index}-${msg.role}-${msg.message_type}`}
              className={`message-row ${
                msg.role === 'user'
                  ? 'message-row-user'
                  : 'message-row-assistant'
              }`}
            >
              {msg.message_type === 'image' &&
                imageSrc && (
                  <div className="image-message">
                    <img
                      src={imageSrc}
                      alt="Uploaded"
                      onClick={() =>
                        setLightboxSrc(imageSrc)
                      }
                    />

                    {msg.content && (
                      <div className="image-caption">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                        >
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>
                )}

              {msg.message_type === 'audio' &&
                audioSrc && (
                  <div
                    className={`audio-message ${
                      msg.role === 'user'
                        ? 'audio-message-user'
                        : 'audio-message-assistant'
                    }`}
                  >
                    <button
                      type="button"
                      className="audio-play-btn"
                      onClick={() =>
                        toggleAudio(
                          audioSrc,
                          audioId
                        )
                      }
                      aria-label={
                        playingAudio === audioId
                          ? 'Остановить аудио'
                          : 'Воспроизвести аудио'
                      }
                    >
                      {playingAudio === audioId ? (
                        <PauseIcon />
                      ) : (
                        <PlayIcon />
                      )}
                    </button>

                    <div className="audio-message-content">
                      {msg.content && (
                        <div className="audio-transcription">
                          <ReactMarkdown
                            remarkPlugins={[
                              remarkGfm,
                            ]}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                  </div>
                )}

              {msg.message_type !== 'image' &&
                msg.message_type !== 'audio' &&
                msg.content && (
                  <div
                    className={`message-bubble ${
                      msg.role === 'user'
                        ? 'message-user'
                        : 'message-assistant'
                    } ${
                      msg.message_type === 'error'
                        ? 'message-error'
                        : ''
                    }`}
                  >
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
            </div>
          );
        })}

        {isLoading && (
          <div className="message-row message-row-assistant">
            <div className="message-bubble message-assistant typing-bubble">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
      </main>

      {/* ====================================================
          Input
          ==================================================== */}

      <div className="input-area">
        <div className="input-container">
          {!isRecording && (
            <>
              <button
                type="button"
                className="icon-button attachment-button"
                onClick={() =>
                  fileInputRef.current?.click()
                }
                disabled={isLoading}
                aria-label="Прикрепить файл"
              >
                <AttachmentIcon />
              </button>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,audio/*,.m4a,.mp4"
                hidden
                onChange={handleFileSelect}
              />

              <textarea
                ref={textareaRef}
                value={input}
                onChange={(event) =>
                  setInput(event.target.value)
                }
                onKeyDown={handleKeyDown}
                placeholder="Сообщение..."
                rows={1}
                disabled={isLoading}
              />

              {input.trim() ? (
                <button
                  type="button"
                  className="icon-button send-button"
                  onClick={() => sendMessage()}
                  disabled={isLoading}
                  aria-label="Отправить"
                >
                  <SendIcon />
                </button>
              ) : (
                <button
                  type="button"
                  className="icon-button mic-button"
                  onClick={startRecording}
                  disabled={isLoading}
                  aria-label="Записать аудио"
                >
                  <MicIcon />
                </button>
              )}
            </>
          )}

          {isRecording && (
            <div className="recording-container">
              <button
                type="button"
                className="recording-action recording-cancel"
                onClick={cancelRecording}
                aria-label="Отменить запись"
              >
                <CloseIcon />
              </button>

              <div className="recording-info">
                <div className="recording-dot" />

                <span className="recording-time">
                  {formatRecordingTime(recordingTime)}
                </span>

                <span className="recording-label">
                  Запись...
                </span>
              </div>

              <button
                type="button"
                className="recording-action recording-send"
                onClick={finishRecording}
                aria-label="Отправить аудио"
              >
                <CheckIcon />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ====================================================
          Image lightbox
          ==================================================== */}

      {lightboxSrc && (
        <div
          className="lightbox"
          onClick={() => setLightboxSrc(null)}
        >
          <button
            type="button"
            className="lightbox-close"
            onClick={() => setLightboxSrc(null)}
            aria-label="Закрыть"
          >
            <CloseIcon />
          </button>

          <img
            src={lightboxSrc}
            alt="Preview"
            onClick={(event) =>
              event.stopPropagation()
            }
          />
        </div>
      )}
    </div>
  );
}