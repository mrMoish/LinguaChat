import {
  useState,
  useRef,
  useEffect,
  useLayoutEffect,
} from 'react';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import './App.css';
import { resizeImageIfNeeded } from './utils/image';


// ============================================================
// IndexedDB
// ============================================================

const DB_NAME = 'linguachat';
const STORE_NAME = 'images';

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(
      DB_NAME,
      1
    );

    request.onupgradeneeded = () => {
      const db = request.result;

      if (
        !db.objectStoreNames.contains(
          STORE_NAME
        )
      ) {
        db.createObjectStore(
          STORE_NAME
        );
      }
    };

    request.onsuccess = () => {
      resolve(request.result);
    };

    request.onerror = () => {
      reject(request.error);
    };
  });
}


async function idbGet(key) {
  try {
    const db = await openDB();

    return new Promise(
      (resolve, reject) => {
        const transaction =
          db.transaction(
            STORE_NAME,
            'readonly'
          );

        const store =
          transaction.objectStore(
            STORE_NAME
          );

        const request =
          store.get(key);

        request.onsuccess = () => {
          resolve(request.result);
        };

        request.onerror = () => {
          reject(request.error);
        };
      }
    );
  } catch {
    return null;
  }
}


async function idbSet(
  key,
  value
) {
  try {
    const db = await openDB();

    return new Promise(
      (resolve, reject) => {
        const transaction =
          db.transaction(
            STORE_NAME,
            'readwrite'
          );

        const store =
          transaction.objectStore(
            STORE_NAME
          );

        const request =
          store.put(
            value,
            key
          );

        request.onsuccess = () => {
          resolve();
        };

        request.onerror = () => {
          reject(request.error);
        };
      }
    );
  } catch {
    // Ignore IndexedDB errors.
  }
}


// ============================================================
// Constants
// ============================================================

const PAGE_SIZE = 20;
const STORAGE_VERSION = 'v2';
const CHAT_HISTORY_STORAGE_KEY =
  `translator_chat_history_${STORAGE_VERSION}`;
const SESSION_STORAGE_KEY =
  `translator_session_id_${STORAGE_VERSION}`;

const WELCOME_MESSAGES = [
  'Я AI-переводчик, который также поможет тебе учить язык',
];

const LEARNER_LEVELS = [
  'unknown',
  'beginner',
  'elementary',
  'intermediate',
  'upper_intermediate',
];

function getStoredLearnerLevel() {
  const value = localStorage.getItem(
    'translator_learner_level'
  );

  return LEARNER_LEVELS.includes(value)
    ? value
    : 'unknown';
}

function normalizeMessageContent(content) {
  return String(content || '')
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\n');
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}


// ============================================================
// Helpers
// ============================================================

function loadCachedMessages() {
  try {
    const saved =
      localStorage.getItem(
        CHAT_HISTORY_STORAGE_KEY
      );

    if (!saved) {
      return [];
    }

    const parsed =
      JSON.parse(saved);

    return Array.isArray(parsed)
      ? parsed
      : [];

  } catch {
    return [];
  }
}


function formatRecordingTime(
  seconds
) {
  const minutes =
    Math.floor(
      seconds / 60
    );

  const remainingSeconds =
    seconds % 60;

  return `${String(
    minutes
  ).padStart(
    2,
    '0'
  )}:${String(
    remainingSeconds
  ).padStart(
    2,
    '0'
  )}`;
}


// ============================================================
// Welcome
// ============================================================

function Welcome({
  texts,
  exercises,
  isLoadingNextExercise,
  matchingStates,
  onMatchingTermClick,
}) {
  return (
    <div className="welcome-message">
      <div className="welcome-bubble message-bubble message-assistant">
        {texts.map((message) => (
          <div key={message}>{message}</div>
        ))}
      </div>

      {exercises.map((exercise, index) => (
        <ExerciseArea
          key={index}
          exercise={exercise}
          answered={exercise.exerciseAnswered}
          correct={exercise.exerciseCorrect}
          userAnswer={exercise.exerciseUserAnswer}
          matchingState={
            matchingStates[
              matchingStateKey(-2, index)
            ]
          }
          onMatchingTermClick={(term, side = 'term') =>
            onMatchingTermClick(index, term, side)
          }
        />
      ))}

      {isLoadingNextExercise && (
        <div
          className="exercise-loading"
          role="status"
          aria-live="polite"
        >
          <span className="exercise-loading-dot" />
          Готовлю следующее упражнение…
        </div>
      )}
    </div>
  );
}


// ============================================================
// Icons
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
      <rect
        x="9"
        y="2"
        width="6"
        height="12"
        rx="3"
      />

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
      <rect
        x="7"
        y="5"
        width="4"
        height="14"
        rx="1"
      />

      <rect
        x="13"
        y="5"
        width="4"
        height="14"
        rx="1"
      />
    </svg>
  );
}


// ============================================================
// Exercise
// ============================================================

function getExerciseItems(message) {
  if (Array.isArray(message?.exercise)) {
    return message.exercise;
  }

  if (Array.isArray(message?.exercises)) {
    return message.exercises;
  }

  if (message?.exercise) {
    return [
      {
        ...message.exercise,
        exerciseAnswered:
          message.exerciseAnswered || false,
        exerciseUserAnswer:
          message.exerciseUserAnswer || null,
        exerciseCorrect:
          message.exerciseCorrect ?? null,
      },
    ];
  }

  return [];
}

function getExerciseOptions(exercise) {
  if (
    exercise?.type !== 'translation_choice' ||
    !Array.isArray(exercise.options) ||
    exercise.options.length !== 2
  ) {
    return [];
  }

  return exercise.options;
}

function getMatchingPairs(exercise) {
  if (
    exercise?.type !== 'matching_pairs' ||
    !Array.isArray(exercise.pairs) ||
    exercise.pairs.length < 2 ||
    exercise.pairs.length > 5
  ) {
    return [];
  }

  return exercise.pairs;
}

function getMatchingTranslations(exercise) {
  const pairs = getMatchingPairs(exercise);
  const translations = Array.isArray(exercise?.translations)
    ? exercise.translations
    : pairs.map((pair) => pair.translation);

  return translations.length === pairs.length
    ? translations
    : pairs.map((pair) => pair.translation);
}

function getInitialMatchingOptions(exercise) {
  const pairs = getMatchingPairs(exercise);
  const options = Array.isArray(exercise?.initial_options)
    ? exercise.initial_options
    : [];

  if (options.length >= 2) {
    return options.slice(0, 2);
  }

  const firstPair = pairs[0];
  return firstPair
    ? [
        firstPair.translation,
        ...pairs
          .map((pair) => pair.translation)
          .filter(
            (translation) =>
              translation !== firstPair.translation
          )
          .slice(0, 1),
      ]
    : [];
}

function ExerciseArea({
  exercise,
  answered,
  userAnswer,
  correct,
  matchingState,
  onMatchingTermClick,
}) {
  if (!exercise) {
    return null;
  }

  if (
    typeof exercise !==
    'object'
  ) {
    return null;
  }

  const question =
    exercise.question ||
    exercise.text ||
    'Найди пары';

  const matchingPairs =
    getMatchingPairs(exercise);

  if (matchingPairs.length >= 2) {
    const safeMatchingState = matchingState || {
      selectedTerm: null,
      selectedTranslation: null,
      matchedTerms: [],
      matchedTranslations: [],
      wrongTerm: null,
      wrongTranslation: null,
    };

    const hasInteraction =
      answered ||
      safeMatchingState.selectedTerm ||
      safeMatchingState.selectedTranslation ||
      safeMatchingState.matchedTerms.length > 0 ||
      safeMatchingState.wrongTerm ||
      safeMatchingState.wrongTranslation;
    const isExpanded =
      hasInteraction || exercise.isGeneratedExercise;
    const firstPair = matchingPairs[0];
    const matchingTranslations =
      getMatchingTranslations(exercise);

    return (
      <div
        className={`exercise-area matching-exercise-area ${
          isExpanded
            ? 'matching-exercise-active'
            : ''
        } ${
          answered && correct
            ? 'matching-exercise-complete'
            : ''
        }`}
      >
        <div className="exercise-question">
          {!isExpanded ? (
            <>
              <span>Найди пару: </span>
              <button
                type="button"
                className={`matching-term matching-term-inline ${
                  safeMatchingState.selectedTerm === firstPair.term
                    ? 'matching-term-selected'
                    : ''
                } ${
                  safeMatchingState.wrongTerm === firstPair.term
                    ? 'matching-term-shake'
                    : ''
                }`}
                onClick={() => onMatchingTermClick(firstPair.term)}
              >
                {firstPair.term}
              </button>
            </>
          ) : (
            'Найди пары'
          )}
        </div>

        {answered && safeMatchingState.matchedTerms.length > 0 && (
          <div className="matching-pairs-found">
            {matchingPairs
              .filter((pair) =>
                safeMatchingState.matchedTerms.includes(
                  pair.term
                )
              )
              .map((pair) => (
                <div
                  key={pair.term}
                  className="matching-pair-found"
                >
                  <span>{pair.term}</span>
                  <span>{pair.translation}</span>
                </div>
              ))}
          </div>
        )}

        {!answered && (
          isExpanded ? (
            <div className="matching-grid">
              <div className="matching-column">
                {matchingPairs.map((pair) => {
                  const isMatched =
                    safeMatchingState.matchedTerms.includes(pair.term);
                  return (
                    <button
                      key={pair.term}
                      type="button"
                      className={`matching-term ${
                        safeMatchingState.selectedTerm === pair.term
                          ? 'matching-term-selected'
                          : ''
                      } ${
                        safeMatchingState.wrongTerm === pair.term
                          ? 'matching-term-shake'
                          : ''
                      } ${isMatched ? 'matching-term-matched' : ''}`}
                      disabled={isMatched}
                      onClick={() =>
                        onMatchingTermClick(pair.term, 'term')
                      }
                    >
                      {pair.term}
                    </button>
                  );
                })}
              </div>

              <div className="matching-column">
                {matchingTranslations.map((translation) => {
                  const isMatched =
                    safeMatchingState.matchedTranslations.includes(
                      translation
                    );
                  return (
                    <button
                      key={translation}
                      type="button"
                      className={`matching-term ${
                        safeMatchingState.selectedTranslation ===
                        translation
                          ? 'matching-term-selected'
                          : ''
                      } ${
                        safeMatchingState.wrongTranslation ===
                        translation
                          ? 'matching-term-shake'
                          : ''
                      } ${isMatched ? 'matching-term-matched' : ''}`}
                      disabled={isMatched}
                      onClick={() =>
                        onMatchingTermClick(
                          translation,
                          'translation'
                        )
                      }
                    >
                      {translation}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null
        )}

      </div>
    );
  }

  if (!question) {
    return null;
  }

  return (
    <div
      className={`exercise-area ${
        exercise.isGeneratedExercise
          ? 'exercise-generated'
          : ''
      }`}
    >

      <div className="exercise-question">
        {question}
      </div>

      {answered && (
        <div
          className={
            correct
              ? 'exercise-result exercise-result-correct'
              : 'exercise-result exercise-result-wrong'
          }
        >

          <div>
            {userAnswer === 'already_know'
              ? 'Хорошо, идём дальше'
              : correct
                ? 'Верно'
                : 'Неверно'}
          </div>

          {exercise.explanation && (
            <div className="exercise-explanation">
              {exercise.explanation}
            </div>
          )}

        </div>
      )}

    </div>
  );
}


// ============================================================
// App
// ============================================================

export default function App() {
  const backendUrl =
    import.meta.env
      .VITE_BACKEND_URL || '';

  // ----------------------------------------------------------
  // Messages
  // ----------------------------------------------------------

  const [
    allMessages,
    setAllMessages,
  ] = useState(
    loadCachedMessages
  );

  const [
    visibleMessages,
    setVisibleMessages,
  ] = useState([]);

  const [
    currentPage,
    setCurrentPage,
  ] = useState(1);

  const [
    hasMore,
    setHasMore,
  ] = useState(false);


  // ----------------------------------------------------------
  // Input
  // ----------------------------------------------------------

  const [
    input,
    setInput,
  ] = useState('');

  const [
    isLoading,
    setIsLoading,
  ] = useState(false);


  // ----------------------------------------------------------
  // History
  // ----------------------------------------------------------

  const [
    isSyncingHistory,
    setIsSyncingHistory,
  ] = useState(false);

  const [
    isLoadingMore,
    setIsLoadingMore,
  ] = useState(false);


  const [
    sessionId,
    setSessionId,
  ] = useState(
    () =>
      localStorage.getItem(
        SESSION_STORAGE_KEY
      ) || null
  );

  const [
    learnerLevel,
    setLearnerLevel,
  ] = useState(getStoredLearnerLevel);

  const [
    welcomeExerciseAnswered,
    setWelcomeExerciseAnswered,
  ] = useState(false);

  const [
    welcomeExerciseUserAnswer,
    setWelcomeExerciseUserAnswer,
  ] = useState(null);

  const [
    welcomeExerciseCorrect,
    setWelcomeExerciseCorrect,
  ] = useState(null);

  const [
    welcomeExerciseItems,
    setWelcomeExerciseItems,
  ] = useState([]);

  const [
    isLoadingNextExercise,
    setIsLoadingNextExercise,
  ] = useState(false);

  const [
    matchingStates,
    setMatchingStates,
  ] = useState({});

  const prefetchedNextExercisesRef = useRef({});
  const prefetchInFlightRef = useRef({});

  function getExercisePrefetchKey(messageIndex, exercise) {
    return `${messageIndex}:${
      exercise?.question ||
      exercise?.text ||
      exercise?.pairs?.map((pair) => pair.term).join('|') ||
      'exercise'
    }`;
  }

  useEffect(() => {
    if (
      allMessages.length > 0 ||
      welcomeExerciseItems.length > 0
    ) {
      return;
    }

    let cancelled = false;

    async function loadWelcomeExercise() {
      try {
        const formData = new FormData();
        formData.append(
          'learner_level_hint',
          learnerLevel
        );

        if (sessionId) {
          formData.append('session_id', sessionId);
        }

        const response = await fetch(
          `${backendUrl}/api/welcome-exercise`,
          {
            method: 'POST',
            body: formData,
          }
        );

        if (!response.ok) {
          throw new Error(
            `Welcome exercise request failed: ${response.status}`
          );
        }

        const data = await response.json();

        if (cancelled || !data.exercise) {
          return;
        }

        setWelcomeExerciseItems([
          {
            ...data.exercise,
            isGeneratedExercise: true,
            exerciseAnswered: false,
            exerciseUserAnswer: null,
            exerciseCorrect: null,
          },
        ]);

        if (data.session_id) {
          setSessionId(data.session_id);
          localStorage.setItem(
            SESSION_STORAGE_KEY,
            data.session_id
          );
        }
      } catch (error) {
        console.error(
          'Failed to load welcome exercise:',
          error
        );
      }
    }

    loadWelcomeExercise();

    return () => {
      cancelled = true;
    };
  }, [
    allMessages.length,
    backendUrl,
    learnerLevel,
    sessionId,
    welcomeExerciseItems.length,
  ]);


  // ----------------------------------------------------------
  // UI
  // ----------------------------------------------------------

  const [
    lightboxSrc,
    setLightboxSrc,
  ] = useState(null);


  // ----------------------------------------------------------
  // PWA
  // ----------------------------------------------------------

  const [
    deferredPrompt,
    setDeferredPrompt,
  ] = useState(null);

  const [
    isAppInstalled,
    setIsAppInstalled,
  ] = useState(false);

  const [
    isAndroid,
    setIsAndroid,
  ] = useState(false);


  // ----------------------------------------------------------
  // Recording
  // ----------------------------------------------------------

  const [
    isRecording,
    setIsRecording,
  ] = useState(false);

  const [
    recordingTime,
    setRecordingTime,
  ] = useState(0);


  const mediaRecorderRef =
    useRef(null);

  const audioChunksRef =
    useRef([]);

  const timerRef =
    useRef(null);


  // ----------------------------------------------------------
  // Audio playback
  // ----------------------------------------------------------

  const [
    playingAudio,
    setPlayingAudio,
  ] = useState(null);

  const audioRef =
    useRef(null);


  // ----------------------------------------------------------
  // Refs
  // ----------------------------------------------------------

  const chatContainerRef =
    useRef(null);

  const fileInputRef =
    useRef(null);

  const textareaRef =
    useRef(null);

  const isNearBottomRef =
    useRef(true);


  // ==========================================================
  // PWA
  // ==========================================================

  useEffect(() => {
    const android =
      /Android/i.test(
        navigator.userAgent || ''
      );

    setIsAndroid(android);

    const standalone =
      window.matchMedia(
        '(display-mode: standalone)'
      ).matches ||
      window.navigator.standalone === true;

    if (standalone) {
      setIsAppInstalled(true);
    }

    function handleBeforeInstallPrompt(
      event
    ) {
      if (!android) {
        return;
      }

      event.preventDefault();

      setDeferredPrompt(event);
    }

    function handleAppInstalled() {
      setIsAppInstalled(true);
      setDeferredPrompt(null);
    }

    window.addEventListener(
      'beforeinstallprompt',
      handleBeforeInstallPrompt
    );

    window.addEventListener(
      'appinstalled',
      handleAppInstalled
    );

    return () => {
      window.removeEventListener(
        'beforeinstallprompt',
        handleBeforeInstallPrompt
      );

      window.removeEventListener(
        'appinstalled',
        handleAppInstalled
      );
    };
  }, []);


  async function handleInstallClick() {
    if (!deferredPrompt) {
      return;
    }

    deferredPrompt.prompt();

    try {
      await deferredPrompt.userChoice;
    } finally {
      setDeferredPrompt(null);
    }
  }


  // ==========================================================
  // Cache
  // ==========================================================

  useEffect(() => {
    try {
      localStorage.setItem(
        CHAT_HISTORY_STORAGE_KEY,
        JSON.stringify(
          allMessages
        )
      );
    } catch {
      // Ignore storage errors.
    }
  }, [allMessages]);


  // ==========================================================
  // Visible messages
  // ==========================================================

  useEffect(() => {
    const total =
      allMessages.length;

    const start =
      Math.max(
        0,
        total -
          PAGE_SIZE *
            currentPage
      );

    setVisibleMessages(
      allMessages.slice(start)
    );

    setHasMore(
      start > 0
    );
  }, [
    allMessages,
    currentPage,
  ]);


  // ==========================================================
  // History sync
  // ==========================================================

  useEffect(() => {
    if (!sessionId) {
      return;
    }

    let cancelled = false;

    async function loadHistory() {
      setIsSyncingHistory(true);

      try {
        const response =
          await fetch(
            `${backendUrl}/api/history?session_id=${encodeURIComponent(
              sessionId
            )}`,
            {
              headers: {
                'X-Session-Id':
                  sessionId,
              },
            }
          );

        if (!response.ok) {
          throw new Error(
            `History request failed: ${response.status}`
          );
        }

        const data =
          await response.json();

        if (cancelled) {
          return;
        }

        if (
          Array.isArray(
            data.messages
          )
        ) {
          const messages = [];

          for (
            const message of
            data.messages
          ) {
            let image = null;

            if (
              message.message_type ===
                'image' &&
              message.media_url
            ) {
              image =
                message.media_url;
            }

            messages.push({
              assistant_message_id:
                message.role === 'assistant'
                  ? message.id || null
                  : null,

              role:
                message.role,

              content:
                message.content ||
                '',

              message_type:
                message.message_type ||
                'text',

              media_url:
                message.media_url ||
                null,

              image,

              audio: null,

              exercise:
                message.exercise ||
                null,

              exerciseAnswered:
                false,

              exerciseUserAnswer:
                null,

              exerciseCorrect:
                null,
            });
          }

          setAllMessages(
            (
              previousMessages
            ) => {
              return messages.map(
                (
                  message,
                  index
                ) => {
                  const previousMessage =
                    previousMessages[
                      index
                    ];

                  const merged = {
                    ...message,
                  };

                  // An unanswered exercise is intentionally not stored in the
                  // backend yet. Preserve it while history is being refreshed,
                  // otherwise the first exercise disappears immediately after
                  // the assistant response.
                  const previousExercises =
                    getExerciseItems(previousMessage);
                  const historyExercises =
                    getExerciseItems(message);

                  const sameMessage =
                    previousMessage?.role === message.role &&
                    previousMessage?.content === message.content;

                  if (
                    sameMessage &&
                    previousExercises.length > historyExercises.length
                  ) {
                    merged.exercises = previousExercises;
                    merged.exercise = null;
                  } else if (
                    sameMessage &&
                    previousExercises.length > 0 &&
                    historyExercises.length === 0
                  ) {
                    merged.exercises = previousExercises;
                    merged.exercise = null;
                  }

                  if (
                    message.message_type ===
                      'image' &&
                    previousMessage?.image &&
                    /^(blob:|data:)/.test(
                      previousMessage.image
                    )
                  ) {
                    merged.image =
                      previousMessage.image;
                  }

                  if (
                    message.message_type ===
                      'audio' &&
                    !message.media_url &&
                    previousMessage?.audio
                  ) {
                    merged.audio =
                      previousMessage.audio;
                  }

                  if (
                    previousMessage?.exerciseAnswered
                  ) {
                    merged.exerciseAnswered =
                      previousMessage.exerciseAnswered;

                    merged.exerciseUserAnswer =
                      previousMessage.exerciseUserAnswer;

                    merged.exerciseCorrect =
                      previousMessage.exerciseCorrect;
                  }

                  if (
                    Array.isArray(
                      previousMessage?.exercises
                    ) &&
                    previousMessage.exercises.length > 0
                  ) {
                    merged.exercises =
                      previousMessage.exercises;
                  }

                  return merged;
                }
              );
            }
          );

          setCurrentPage(1);
        }

      } catch (error) {

        console.error(
          'Failed to load history:',
          error
        );

      } finally {

        if (!cancelled) {
          setIsSyncingHistory(
            false
          );
        }
      }
    }

    loadHistory();

    return () => {
      cancelled = true;
    };

  }, [
    sessionId,
    backendUrl,
  ]);


  // ==========================================================
  // Initial scroll
  // ==========================================================

  useLayoutEffect(() => {
    if (
      visibleMessages.length ===
      0
    ) {
      return;
    }

    window.scrollTo({
      top:
        document.documentElement
          .scrollHeight,
      behavior: 'auto',
    });

  }, []);


  // ==========================================================
  // Auto scroll
  // ==========================================================

  useEffect(() => {
    if (
      !isNearBottomRef.current
    ) {
      return;
    }

    if (
      visibleMessages.length ===
      0
    ) {
      return;
    }

    const timer =
      setTimeout(() => {
        window.scrollTo({
          top:
            document.documentElement
              .scrollHeight,
          behavior: 'smooth',
        });
      }, 50);

    return () =>
      clearTimeout(timer);

  }, [
    visibleMessages.length,
    isLoading,
  ]);


  // ==========================================================
  // Scroll
  // ==========================================================

  useEffect(() => {
    function handleScroll() {
      const scrollTop =
        window.scrollY;

      const viewportBottom =
        window.innerHeight +
        window.scrollY;

      const documentHeight =
        document.documentElement
          .scrollHeight;

      isNearBottomRef.current =
        documentHeight -
          viewportBottom <
        180;

      if (
        scrollTop < 200 &&
        hasMore &&
        !isLoadingMore
      ) {
        setIsLoadingMore(true);

        setTimeout(() => {
          setCurrentPage(
            (page) =>
              page + 1
          );

          setIsLoadingMore(false);
        }, 100);
      }
    }

    window.addEventListener(
      'scroll',
      handleScroll
    );

    return () => {
      window.removeEventListener(
        'scroll',
        handleScroll
      );
    };
  }, [
    hasMore,
    isLoadingMore,
  ]);


  // ==========================================================
  // Cleanup audio
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
  // Textarea
  // ==========================================================

  useEffect(() => {
    const textarea =
      textareaRef.current;

    if (!textarea) {
      return;
    }

    textarea.style.height =
      'auto';

    textarea.style.height =
      `${Math.min(
        textarea.scrollHeight,
        140
      )}px`;

  }, [input]);


  // ==========================================================
  // Audio playback
  // ==========================================================

  function toggleAudio(
    src,
    messageId
  ) {
    if (!src) {
      return;
    }

    if (
      playingAudio ===
        messageId &&
      audioRef.current
    ) {
      audioRef.current.pause();

      audioRef.current.currentTime =
        0;

      audioRef.current = null;

      setPlayingAudio(null);

      return;
    }

    if (audioRef.current) {
      audioRef.current.pause();

      audioRef.current.currentTime =
        0;

      audioRef.current = null;
    }

    const audio =
      new Audio(src);

    audioRef.current =
      audio;

    audio.onended = () => {
      setPlayingAudio(null);
      audioRef.current = null;
    };

    audio.onerror = () => {
      setPlayingAudio(null);
      audioRef.current = null;
    };

    setPlayingAudio(
      messageId
    );

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

    timerRef.current =
      setInterval(() => {
        setRecordingTime(
          (time) =>
            time + 1
        );
      }, 1000);
  }


  function stopRecordingTimer() {
    if (timerRef.current) {
      clearInterval(
        timerRef.current
      );

      timerRef.current = null;
    }
  }


  // ==========================================================
  // Start recording
  // ==========================================================

  async function startRecording() {
    if (
      isRecording ||
      isLoading
    ) {
      return;
    }

    try {

      const stream =
        await navigator
          .mediaDevices
          .getUserMedia({
            audio: true,
          });

      const recorder =
        new MediaRecorder(
          stream
        );

      mediaRecorderRef.current =
        recorder;

      audioChunksRef.current =
        [];

      recorder.ondataavailable =
        (event) => {
          if (
            event.data.size > 0
          ) {
            audioChunksRef.current.push(
              event.data
            );
          }
        };

      recorder.onstop = () => {
        stream
          .getTracks()
          .forEach(
            (track) => {
              track.stop();
            }
          );
      };

      recorder.start();

      setIsRecording(true);

      startRecordingTimer();

    } catch (error) {

      console.error(
        'Microphone error:',
        error
      );

      alert(
        'Не удалось получить доступ к микрофону.'
      );
    }
  }


  // ==========================================================
  // Cancel recording
  // ==========================================================

  function cancelRecording() {
    const recorder =
      mediaRecorderRef.current;

    if (
      recorder &&
      recorder.state !==
        'inactive'
    ) {
      recorder.ondataavailable =
        null;

      recorder.stop();
    }

    mediaRecorderRef.current =
      null;

    audioChunksRef.current =
      [];

    stopRecordingTimer();

    setRecordingTime(0);

    setIsRecording(false);
  }


  // ==========================================================
  // Finish recording
  // ==========================================================

  function finishRecording() {
    const recorder =
      mediaRecorderRef.current;

    if (
      !recorder ||
      recorder.state ===
        'inactive'
    ) {
      return;
    }

    recorder.onstop = () => {
      const stream =
        recorder.stream;

      stream
        .getTracks()
        .forEach(
          (track) => {
            track.stop();
          }
        );

      const blob =
        new Blob(
          audioChunksRef.current,
          {
            type:
              recorder.mimeType ||
              'audio/webm',
          }
        );

      mediaRecorderRef.current =
        null;

      audioChunksRef.current =
        [];

      stopRecordingTimer();

      setRecordingTime(0);

      setIsRecording(false);

      if (blob.size > 0) {
        sendMessage(
          '',
          blob
        );
      }
    };

    recorder.stop();
  }


  // ==========================================================
  // Exercise answer
  // ==========================================================

  async function handleWelcomeExerciseAnswer(answer) {
    const exerciseIndex =
      welcomeExerciseItems.length - 1;
    const exercise =
      welcomeExerciseItems[exerciseIndex];

    if (!exercise || exercise.exerciseAnswered) {
      return;
    }

    const isMatching =
      getMatchingPairs(exercise).length >= 2;

    const correct = isMatching
      ? answer === 'matching_complete'
      : answer === exercise.correct_answer;

    setWelcomeExerciseAnswered(true);
    setWelcomeExerciseUserAnswer(answer);
    setWelcomeExerciseCorrect(correct);

    setWelcomeExerciseItems((items) => {
      const updated = [...items];
      updated[exerciseIndex] = {
        ...exercise,
        exerciseAnswered: true,
        exerciseUserAnswer: answer,
        exerciseCorrect: correct,
      };
      return updated;
    });

    setIsLoadingNextExercise(true);

    const prefetchKey = getExercisePrefetchKey(
      -2,
      exercise
    );
    const prefetchedExercise =
      prefetchedNextExercisesRef.current[prefetchKey];

    if (prefetchedExercise) {
      delete prefetchedNextExercisesRef.current[prefetchKey];
      setWelcomeExerciseItems((items) => [
        ...items,
        {
          ...prefetchedExercise,
          isGeneratedExercise: true,
          exerciseAnswered: false,
          exerciseUserAnswer: null,
          exerciseCorrect: null,
        },
      ]);
      setIsLoadingNextExercise(false);
      return;
    }

    try {
      const formData = new FormData();
      formData.append(
        'learner_level_hint',
        learnerLevel
      );
      formData.append(
        'answered_exercise',
        JSON.stringify({
          ...exercise,
          exerciseAnswered: true,
          exerciseUserAnswer: answer,
          exerciseCorrect: correct,
        })
      );

      if (sessionId) {
        formData.append('session_id', sessionId);
      }

      const response = await fetch(
        `${backendUrl}/api/exercise`,
        {
          method: 'POST',
          body: formData,
        }
      );

      if (!response.ok) {
        throw new Error(
          `Welcome next exercise failed: ${response.status}`
        );
      }

      const data = await response.json();

      if (data.exercise) {
        setWelcomeExerciseItems((items) => [
          ...items,
          {
            ...data.exercise,
            exerciseAnswered: false,
            exerciseUserAnswer: null,
            exerciseCorrect: null,
          },
        ]);
      }
    } catch (error) {
      console.error(
        'Failed to generate next welcome exercise:',
        error
      );
    } finally {
      setIsLoadingNextExercise(false);
    }
  }

  function matchingStateKey(
    messageIndex,
    exerciseIndex
  ) {
    return `${messageIndex}:${exerciseIndex}`;
  }

  async function prefetchNextExercise(
    messageIndex,
    translation,
    sourceText,
    answeredExercise
  ) {
    const key = getExercisePrefetchKey(
      messageIndex,
      answeredExercise
    );

    if (prefetchedNextExercisesRef.current[key]) {
      return;
    }

    if (prefetchInFlightRef.current[key]) {
      return;
    }

    prefetchInFlightRef.current[key] = true;

    try {
      const formData = new FormData();
      formData.append('translation', translation || '');
      formData.append('source_text', sourceText || '');
      formData.append('learner_level_hint', learnerLevel);
      formData.append(
        'answered_exercise',
        JSON.stringify(answeredExercise)
      );

      if (sessionId) {
        formData.append('session_id', sessionId);
      }

      const response = await fetch(
        `${backendUrl}/api/exercise`,
        {
          method: 'POST',
          body: formData,
        }
      );

      if (!response.ok) {
        return;
      }

      const data = await response.json();

      if (data.exercise) {
        prefetchedNextExercisesRef.current[key] = data.exercise;
      }
    } catch (error) {
      console.error(
        'Failed to prefetch next exercise:',
        error
      );
    } finally {
      delete prefetchInFlightRef.current[key];
    }
  }

  async function handleMatchingClick(
    messageIndex,
    exerciseIndex,
    side,
    value
  ) {
    const message =
      messageIndex === -2
        ? null
        : allMessages[messageIndex];
    const exercise =
      messageIndex === -2
        ? welcomeExerciseItems[exerciseIndex]
        : getExerciseItems(message)[exerciseIndex];
    const pairs = getMatchingPairs(exercise);

    if (!exercise || pairs.length < 2) {
      return;
    }

    const key = matchingStateKey(
      messageIndex,
      exerciseIndex
    );
    const current = matchingStates[key] || {
      selectedTerm: null,
      selectedTranslation: null,
      matchedTerms: [],
      matchedTranslations: [],
      wrongTerm: null,
      wrongTranslation: null,
    };

    const hasStarted = Boolean(
      current.selectedTerm ||
      current.selectedTranslation ||
      current.matchedTerms.length ||
      current.wrongTerm ||
      current.wrongTranslation
    );

    if (!hasStarted) {
      void prefetchNextExercise(
        messageIndex,
        message?.content || WELCOME_MESSAGES.join(' '),
        messageIndex > 0
          ? allMessages[messageIndex - 1]?.content || ''
          : '',
        exercise
      );
    }

    if (
      side === 'term' &&
      current.matchedTerms.includes(value)
    ) {
      return;
    }

    if (
      side === 'translation' &&
      current.matchedTranslations.includes(value)
    ) {
      return;
    }

    const next = {
      ...current,
      wrongTerm: null,
      wrongTranslation: null,
    };

    if (side === 'term') {
      next.selectedTerm = value;
    } else {
      next.selectedTranslation = value;
    }

    if (
      next.selectedTerm &&
      next.selectedTranslation
    ) {
      const pair = pairs.find(
        (item) => item.term === next.selectedTerm
      );
      const isCorrect =
        pair?.translation === next.selectedTranslation;

      if (isCorrect) {
        next.matchedTerms = [
          ...next.matchedTerms,
          next.selectedTerm,
        ];
        next.matchedTranslations = [
          ...next.matchedTranslations,
          next.selectedTranslation,
        ];
        next.selectedTerm = null;
        next.selectedTranslation = null;

        const completed =
          next.matchedTerms.length === pairs.length;

        setMatchingStates((states) => ({
          ...states,
          [key]: next,
        }));

        if (completed) {
          if (messageIndex === -2) {
            await handleWelcomeExerciseAnswer(
              'matching_complete'
            );
          } else {
            await handleExerciseAnswer(
              messageIndex,
              exerciseIndex,
              'matching_complete'
            );
          }
        }

        return;
      }

      next.wrongTerm = next.selectedTerm;
      next.wrongTranslation = next.selectedTranslation;
      next.selectedTerm = null;
      next.selectedTranslation = null;

      setMatchingStates((states) => ({
        ...states,
        [key]: next,
      }));

      window.setTimeout(() => {
        setMatchingStates((states) => ({
          ...states,
          [key]: {
            ...states[key],
            wrongTerm: null,
            wrongTranslation: null,
          },
        }));
      }, 500);

      return;
    }

    setMatchingStates((states) => ({
      ...states,
      [key]: next,
    }));
  }

  async function requestNextExercise(
    messageIndex,
    translation,
    sourceText,
    levelHint,
    assistantMessageId,
    answeredExercise
  ) {
    const prefetchKey = getExercisePrefetchKey(
      messageIndex,
      answeredExercise
    );

    const appendExercise = (nextExercise) => {
      setAllMessages((messages) => {
        const updated = [...messages];
        const message = updated[messageIndex];

        if (!message) {
          return messages;
        }

        const exercises = getExerciseItems(message);
        const newQuestion = String(
          nextExercise.question ||
          nextExercise.text ||
          ''
        ).trim();

        if (
          newQuestion &&
          exercises.some(
            (item) =>
              String(
                item.question || item.text || ''
              ).trim() === newQuestion
          )
        ) {
          return messages;
        }

        updated[messageIndex] = {
          ...message,
          exercises: [
            ...exercises,
            {
              ...nextExercise,
              isGeneratedExercise: true,
            },
          ],
        };

        return updated;
      });
    };

    const prefetchedExercise =
      prefetchedNextExercisesRef.current[prefetchKey];

    if (prefetchedExercise) {
      delete prefetchedNextExercisesRef.current[prefetchKey];
      appendExercise(prefetchedExercise);
      return;
    }

    setIsLoadingNextExercise(true);

    try {
      const formData = new FormData();

      formData.append('translation', translation || '');
      formData.append('source_text', sourceText || '');
      formData.append('learner_level_hint', levelHint);

      if (assistantMessageId) {
        formData.append(
          'assistant_message_id',
          String(assistantMessageId)
        );
      }

      formData.append(
        'answered_exercise',
        JSON.stringify(answeredExercise)
      );

      if (sessionId) {
        formData.append('session_id', sessionId);
      }

      const headers = sessionId
        ? { 'X-Session-Id': sessionId }
        : {};

      const response = await fetch(
        `${backendUrl}/api/exercise`,
        {
          method: 'POST',
          headers,
          body: formData,
        }
      );

      if (!response.ok) {
        throw new Error(
          `Exercise request failed: ${response.status}`
        );
      }

      const data = await response.json();

      if (!data.exercise) {
        return;
      }

      appendExercise(data.exercise);
    } catch (error) {
      console.error(
        'Next exercise request failed:',
        error
      );
    } finally {
      setIsLoadingNextExercise(false);
    }
  }


  async function handleExerciseAnswer(
    messageIndex,
    exerciseIndex,
    answer
  ) {
    const message = allMessages[messageIndex];
    const exercises = getExerciseItems(message);
    const exercise = exercises[exerciseIndex];

    if (
      !message ||
      !exercise ||
      exercise.exerciseAnswered
    ) {
      return;
    }

    const correctAnswer =
      exercise.correct_answer ||
      exercise.answer;

    const isMatching =
      getMatchingPairs(exercise).length >= 2;

    if (!correctAnswer && !isMatching) {
      return;
    }

    const correct =
      isMatching
        ? answer === 'matching_complete'
        : answer !== 'already_know' &&
          correctAnswer === answer;

    const currentLevelIndex =
      LEARNER_LEVELS.indexOf(learnerLevel);

    const nextLevel =
      answer === 'already_know'
        ? LEARNER_LEVELS[
            Math.min(
              currentLevelIndex + 1,
              LEARNER_LEVELS.length - 1
            )
          ]
        : !correct
          ? LEARNER_LEVELS[
              Math.max(currentLevelIndex - 1, 0)
            ]
          : learnerLevel;

    setLearnerLevel(nextLevel);
    localStorage.setItem(
      'translator_learner_level',
      nextLevel
    );

    setAllMessages((messages) => {
      const updated = [...messages];
      const current = updated[messageIndex];
      const currentExercises =
        getExerciseItems(current);

      if (!current || !currentExercises[exerciseIndex]) {
        return messages;
      }

      currentExercises[exerciseIndex] = {
        ...currentExercises[exerciseIndex],
        exerciseAnswered: true,
        exerciseUserAnswer: answer,
        exerciseCorrect: correct,
      };

      updated[messageIndex] = {
        ...current,
        exercises: currentExercises,
      };

      return updated;
    });

    await requestNextExercise(
      messageIndex,
      message.content,
      allMessages[messageIndex - 1]?.content,
      nextLevel,
      message.assistant_message_id,
      {
        ...exercise,
        exerciseAnswered: true,
        exerciseUserAnswer: answer,
        exerciseCorrect: correct,
      }
    );
  }


  // ==========================================================
  // Send message
  // ==========================================================

  async function sendMessage(
    text = input,
    file = null
  ) {
    if (isLoading) {
      return;
    }

    const trimmedText =
      text.trim();

    if (
      !trimmedText &&
      !file
    ) {
      return;
    }

    const welcomeExercisesForMessage =
      allMessages.length === 0
        ? welcomeExerciseItems
        : [];

    isNearBottomRef.current =
      true;

    let messageType =
      'text';

    if (file) {

      if (
        file.type.startsWith(
          'image/'
        )
      ) {
        messageType =
          'image';

      } else if (
        file.type.startsWith(
          'audio/'
        )
      ) {
        messageType =
          'audio';
      }
    }


    // --------------------------------------------------------
    // Local media
    // --------------------------------------------------------

    const localMediaUrl =
      file
        ? URL.createObjectURL(
            file
          )
        : null;


    // --------------------------------------------------------
    // Optimistic user message
    // --------------------------------------------------------

    const optimisticMessage = {
      role: 'user',

      content:
        trimmedText || '',

      message_type:
        messageType,

      image:
        messageType === 'image'
          ? localMediaUrl
          : null,

      audio:
        messageType === 'audio'
          ? localMediaUrl
          : null,

      media_url: null,

      exercise: null,

      exerciseAnswered: false,

      exerciseUserAnswer: null,

      exerciseCorrect: null,
    };

    if (
      file &&
      messageType === 'image'
    ) {
      fileToDataUrl(file)
        .then((dataUrl) => {
          setAllMessages((messages) => {
            const updated = [...messages];

            for (let index = updated.length - 1; index >= 0; index -= 1) {
              const message = updated[index];

              if (
                message.role === 'user' &&
                message.message_type === 'image' &&
                message.image === localMediaUrl
              ) {
                updated[index] = {
                  ...message,
                  image: dataUrl,
                };
                break;
              }
            }

            return updated;
          });

          URL.revokeObjectURL(localMediaUrl);
        })
        .catch((error) => {
          console.error(
            'Failed to prepare local image preview:',
            error
          );
        });
    }


    // --------------------------------------------------------
    // Show immediately
    // --------------------------------------------------------

    setAllMessages(
      (messages) => {
        const updated = [
          ...messages,
          optimisticMessage,
        ];

        setVisibleMessages(
          updated.slice(
            -PAGE_SIZE
          )
        );

        return updated;
      }
    );

    setCurrentPage(1);

    setInput('');

    setIsLoading(true);


    try {

      const formData =
        new FormData();

      if (trimmedText) {
        formData.append(
          'text',
          trimmedText
        );
      }

      if (file) {
        formData.append(
          'file',
          file
        );
      }

      if (sessionId) {
        formData.append(
          'session_id',
          sessionId
        );
      }

      if (welcomeExercisesForMessage.length > 0) {
        formData.append(
          'welcome_exercises',
          JSON.stringify(welcomeExercisesForMessage)
        );
      }

      formData.append(
        'learner_level_hint',
        learnerLevel
      );


      const headers = {};

      if (sessionId) {
        headers['X-Session-Id'] =
          sessionId;
      }

      const response =
        await fetch(
          `${backendUrl}/api/message`,
          {
            method: 'POST',
            headers,
            body: formData,
          }
        );


      if (!response.ok) {

        const errorText =
          await response.text();

        throw new Error(
          errorText ||
            `Request failed: ${response.status}`
        );
      }


      const data =
        await response.json();


      // ------------------------------------------------------
      // Session ID
      // ------------------------------------------------------

      if (data.session_id) {

        localStorage.setItem(
          SESSION_STORAGE_KEY,
          data.session_id
        );

        setSessionId(
          data.session_id
        );
      }


      // ------------------------------------------------------
      // Update messages
      // ------------------------------------------------------

      setAllMessages(
        (messages) => {

          const updated = [
            ...messages,
          ];


          // --------------------------------------------------
          // Find latest user message
          // --------------------------------------------------

          const lastUserIndex =
            [...updated]
              .map(
                (
                  message,
                  index
                ) => ({
                  message,
                  index,
                })
              )
              .reverse()
              .find(
                ({
                  message,
                }) =>
                  message.role ===
                  'user'
              )?.index;


          if (
            lastUserIndex !==
            undefined
          ) {

            const current =
              updated[
                lastUserIndex
              ];


            // ----------------------------------------------
            // IMAGE
            // ----------------------------------------------

            if (
              messageType ===
              'image'
            ) {

              updated[
                lastUserIndex
              ] = {
                ...current,

                message_type:
                  'image',

                ...(data.media_url
                  ? {
                      media_url:
                        data.media_url,
                    }
                  : {}),
              };
            }


            // ----------------------------------------------
            // AUDIO
            // ----------------------------------------------

            if (
              messageType ===
              'audio'
            ) {

              updated[
                lastUserIndex
              ] = {
                ...current,

                content:
                  data.transcription ||
                  '',

                media_url:
                  data.media_url ||
                  current.media_url ||
                  null,

                audio:
                  data.media_url ||
                  current.audio ||
                  null,

                message_type:
                  'audio',
              };
            }
          }


          // --------------------------------------------------
          // AI translation
          // --------------------------------------------------

          if (
            data.translation
          ) {

            setWelcomeExerciseItems([]);

            updated.push({
              role:
                'assistant',

              content:
                data.translation,

              assistant_message_id:
                data.assistant_message_id ||
                null,

              message_type:
                'text',

              image: null,

              audio: null,

              media_url: null,

              exercise:
                data.exercise ||
                null,

              exerciseAnswered:
                false,

              exerciseUserAnswer:
                null,

              exerciseCorrect:
                null,

              exercises: [
                ...(data.exercise
                  ? [data.exercise]
                  : []),
              ],
            });
          }


          setVisibleMessages(
            updated.slice(
              -PAGE_SIZE
            )
          );

          return updated;
        }
      );

    } catch (error) {

      console.error(
        'Send message error:',
        error
      );

      setAllMessages(
        (messages) => {

          const updated = [
            ...messages,

            {
              role:
                'assistant',

              content:
                'Не удалось отправить сообщение. Попробуйте ещё раз.',

              message_type:
                'error',

              image: null,

              audio: null,

              media_url: null,

              exercise: null,

              exerciseAnswered: false,

              exerciseUserAnswer: null,

              exerciseCorrect: null,
            },
          ];

          setVisibleMessages(
            updated.slice(
              -PAGE_SIZE
            )
          );

          return updated;
        }
      );

    } finally {

      setIsLoading(false);
    }
  }


  // ==========================================================
  // File selection
  // ==========================================================

  async function handleFileSelect(
    event
  ) {
    const originalFile =
      event.target.files?.[0];

    event.target.value = '';

    if (!originalFile) {
      return;
    }

    const file = await resizeImageIfNeeded(originalFile);

    const maxSize =
      10 * 1024 * 1024;

    if (
      file.size >
      maxSize
    ) {
      alert(
        'Файл слишком большой. Максимальный размер — 10 МБ.'
      );

      return;
    }

    sendMessage(
      '',
      file
    );
  }


  // ==========================================================
  // Retry
  // ==========================================================

  async function handleRetry(
    message
  ) {
    if (
      message.message_type !==
      'image'
    ) {
      return;
    }

    let blob = null;

    const source =
      message.media_url ||
      message.image;

    if (source) {

      try {

        const response =
          await fetch(
            source
          );

        blob =
          await response.blob();

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


  // ==========================================================
  // Keyboard
  // ==========================================================

  function handleKeyDown(
    event
  ) {
    if (
      event.key ===
        'Enter' &&
      !event.shiftKey
    ) {

      event.preventDefault();

      if (
        input.trim()
      ) {
        sendMessage();
      }
    }
  }

  const latestExerciseIndex =
    allMessages.reduceRight(
      (foundIndex, message, index) => {
        if (foundIndex !== -1) {
          return foundIndex;
        }

        if (
          message.role === 'assistant' &&
          getExerciseItems(message).length > 0
        ) {
          return index;
        }

        return -1;
      },
      -1
    );

  const latestExerciseItems =
    latestExerciseIndex === -1
      ? []
      : getExerciseItems(
          allMessages[latestExerciseIndex]
        );

  const activeExerciseItemIndex =
    latestExerciseItems.length > 0 &&
    !latestExerciseItems[
      latestExerciseItems.length - 1
    ].exerciseAnswered
      ? latestExerciseItems.length - 1
      : -1;

  const activeExerciseIndex =
    allMessages.length === 0 &&
    welcomeExerciseItems.some(
      (exercise) => !exercise.exerciseAnswered
    )
      ? -2
      : activeExerciseItemIndex === -1
        ? -1
      : latestExerciseIndex;

  const activeExercise =
    activeExerciseIndex === -2
      ? welcomeExerciseItems[
          welcomeExerciseItems.length - 1
        ]
      : activeExerciseIndex !== -1
        ? getExerciseItems(
            allMessages[activeExerciseIndex]
          )[activeExerciseItemIndex]
        : null;

  const activeMatchingPairs =
    getMatchingPairs(activeExercise);
  const activeMatchingTranslations =
    getMatchingTranslations(activeExercise);
  const activeMatchingState =
    matchingStates[
      matchingStateKey(
        activeExerciseIndex,
        activeExerciseIndex === -2
          ? welcomeExerciseItems.length - 1
          : activeExerciseItemIndex
      )
    ];
  const matchingHasInteraction = Boolean(
    activeMatchingState?.selectedTerm ||
    activeMatchingState?.selectedTranslation ||
    activeMatchingState?.matchedTerms?.length ||
    activeMatchingState?.wrongTerm ||
    activeMatchingState?.wrongTranslation
  );
  const activeExerciseOptions =
    activeMatchingPairs.length > 0
      ? (matchingHasInteraction
          ? activeMatchingTranslations
          : getInitialMatchingOptions(activeExercise)
        )
      : getExerciseOptions(activeExercise);


  // ==========================================================
  // Render
  // ==========================================================

  return (
    <div className="app">

      {/* ======================================================
          PWA
          ====================================================== */}

      {isAndroid &&
        !isAppInstalled &&
        deferredPrompt && (
          <button
            type="button"
            className="install-pwa-button"
            onClick={
              handleInstallClick
            }
            style={{
              position: 'fixed',
              top:
                'calc(15px + env(safe-area-inset-top))',
              right: '15px',
              zIndex: 100,
              border: 'none',
              borderRadius: '20px',
              padding:
                '8px 16px',
              backgroundColor:
                '#333333',
              color:
                '#ffffff',
              fontSize: '14px',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            Установить
          </button>
        )}


      {/* ======================================================
          CHAT
          ====================================================== */}

      <main
        ref={
          chatContainerRef
        }
        className="chat-container"
      >

        {visibleMessages.length ===
          0 && (
          <Welcome
            texts={
              WELCOME_MESSAGES
            }
            exercises={welcomeExerciseItems}
            isLoadingNextExercise={
              isLoadingNextExercise
            }
            matchingStates={matchingStates}
            onMatchingTermClick={(
              index,
              term,
              side = 'term'
            ) =>
              handleMatchingClick(
                -2,
                index,
                side,
                term
              )
            }
          />
        )}


        {isLoadingMore && (
          <div className="loading-more">
            Загрузка...
          </div>
        )}


        {visibleMessages.map(
          (
            msg,
            index
          ) => {

            const imageSrc =
              msg.image ||
              (
                msg.message_type ===
                'image'
                  ? msg.media_url
                  : null
              );

            const audioSrc =
              msg.audio ||
              (
                msg.message_type ===
                'audio'
                  ? msg.media_url
                  : null
              );

            const audioId =
              `${index}-${msg.role}-${msg.message_type}`;


            const globalIndex =
              allMessages.length -
              visibleMessages.length +
              index;


            return (
              <div
                key={`${globalIndex}-${msg.role}-${msg.message_type}`}
                className={`message-row ${
                  msg.role ===
                  'user'
                    ? 'message-row-user'
                    : 'message-row-assistant'
                }`}
              >

                {/* ==========================================
                    IMAGE
                    ========================================== */}

                {msg.message_type ===
                  'image' &&
                  imageSrc && (
                    <div className="image-message">

                      <img
                        src={imageSrc}
                        alt="Uploaded"
                        onClick={() =>
                          setLightboxSrc(
                            imageSrc
                          )
                        }
                      />

                      {msg.content && (
                        <div className="image-caption">
                          <ReactMarkdown
                            remarkPlugins={[
                              remarkGfm,
                            ]}
                          >
                            {
                              normalizeMessageContent(
                                msg.content
                              )
                            }
                          </ReactMarkdown>
                        </div>
                      )}

                    </div>
                  )}


                {/* ==========================================
                    AUDIO
                    ========================================== */}

                {msg.message_type ===
                  'audio' &&
                  audioSrc && (
                    <div
                      className={`audio-message ${
                        msg.role ===
                        'user'
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
                          playingAudio ===
                          audioId
                            ? 'Остановить аудио'
                            : 'Воспроизвести аудио'
                        }
                      >

                        {playingAudio ===
                        audioId ? (
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
                              {
                              normalizeMessageContent(
                                msg.content
                              )
                              }
                            </ReactMarkdown>

                          </div>
                        )}

                      </div>

                    </div>
                  )}


                {/* ==========================================
                    NORMAL MESSAGE
                    ========================================== */}

                {msg.message_type !==
                  'image' &&
                  msg.message_type !==
                    'audio' &&
                  msg.content && (

                    <div
                      className={`message-bubble ${
                        msg.role ===
                        'user'
                          ? 'message-user'
                          : 'message-assistant'
                      } ${
                        msg.message_type ===
                        'error'
                          ? 'message-error'
                          : ''
                      }`}
                    >

                      <ReactMarkdown
                        remarkPlugins={[
                          remarkGfm,
                        ]}
                      >
                        {
                        normalizeMessageContent(
                          msg.content
                        )
                        }
                      </ReactMarkdown>

                    </div>
                  )}


                {/* ==========================================
                    EXERCISE
                    ========================================== */}

                {msg.role ===
                  'assistant' &&
                  getExerciseItems(msg)
                    .filter(
                      (exercise) =>
                        exercise.exerciseAnswered ||
                        globalIndex === latestExerciseIndex
                    )
                    .map(
                    (exercise, exerciseIndex) => (
                      <ExerciseArea
                        key={exerciseIndex}
                        exercise={exercise}
                        answered={
                          exercise.exerciseAnswered
                        }
                        userAnswer={
                          exercise.exerciseUserAnswer
                        }
                        correct={
                          exercise.exerciseCorrect
                        }
                        matchingState={
                          matchingStates[
                            matchingStateKey(
                              globalIndex,
                              exerciseIndex
                            )
                          ]
                        }
                        onMatchingTermClick={(
                          term,
                          side = 'term'
                        ) =>
                          handleMatchingClick(
                            globalIndex,
                            exerciseIndex,
                            side,
                            term
                          )
                        }
                      />
                    )
                    )
                  }

                {msg.role === 'assistant' &&
                  globalIndex === latestExerciseIndex &&
                  isLoadingNextExercise && (
                    <div
                      className="exercise-loading"
                      role="status"
                      aria-live="polite"
                    >
                      <span className="exercise-loading-dot" />
                      Готовлю следующее упражнение…
                    </div>
                  )}

              </div>
            );
          }
        )}


        {/* ====================================================
            TYPING
            ==================================================== */}

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

      {activeExerciseIndex !== -1 && !(
        activeMatchingPairs.length > 0 &&
        (matchingHasInteraction || activeExercise?.isGeneratedExercise)
      ) && (
        <div className="exercise-actions">
          <div className="exercise-actions-inner">
            {activeMatchingPairs.length > 0 || activeExerciseOptions.length === 2
              ? activeExerciseOptions.map((option) => {
                  const matchingState =
                    matchingStates[
                      matchingStateKey(
                        activeExerciseIndex,
                        activeExerciseIndex === -2
                          ? welcomeExerciseItems.length - 1
                          : activeExerciseItemIndex
                      )
                    ];
                  const isMatchedTranslation =
                    matchingState?.matchedTranslations?.includes(
                      option
                    );

                  return (
                    <button
                      key={option}
                      type="button"
                      className="exercise-button"
                      disabled={isMatchedTranslation}
                      onClick={() =>
                        getMatchingPairs(activeExercise).length > 0
                          ? handleMatchingClick(
                              activeExerciseIndex,
                              activeExerciseIndex === -2
                                ? welcomeExerciseItems.length - 1
                                : activeExerciseItemIndex,
                              'translation',
                              option
                            )
                          : activeExerciseIndex === -2
                          ? handleWelcomeExerciseAnswer(
                              option
                            )
                          : handleExerciseAnswer(
                              activeExerciseIndex,
                              activeExerciseItemIndex,
                              option
                            )
                      }
                    >
                      {option}
                    </button>
                  );
                })
              : (
                <>
                  <button
                    type="button"
                    className="exercise-button"
                    onClick={() =>
                      activeExerciseIndex === -2
                        ? handleWelcomeExerciseAnswer(
                            'yes'
                          )
                        : handleExerciseAnswer(
                            activeExerciseIndex,
                            activeExerciseItemIndex,
                            'yes'
                          )
                    }
                  >
                    Да
                  </button>

                  <button
                    type="button"
                    className="exercise-button"
                    onClick={() =>
                      activeExerciseIndex === -2
                        ? handleWelcomeExerciseAnswer(
                            'no'
                          )
                        : handleExerciseAnswer(
                            activeExerciseIndex,
                            activeExerciseItemIndex,
                            'no'
                          )
                    }
                  >
                    Нет
                  </button>
                </>
              )}

            {activeExerciseOptions.length !== 2 &&
              learnerLevel === 'unknown' && (
              <button
                type="button"
                className="exercise-button"
                onClick={() =>
                  activeExerciseIndex === -2
                    ? handleWelcomeExerciseAnswer(
                        'already_know'
                      )
                    : handleExerciseAnswer(
                        activeExerciseIndex,
                        activeExerciseItemIndex,
                        'already_know'
                      )
                }
              >
                Я это уже знаю
              </button>
            )}
          </div>
        </div>
      )}


      {/* ======================================================
          INPUT
          ====================================================== */}

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
                disabled={
                  isLoading
                }
                aria-label="Прикрепить файл"
              >
                <AttachmentIcon />
              </button>


              <input
                ref={
                  fileInputRef
                }
                type="file"
                accept="image/*,audio/*,.m4a,.mp4"
                hidden
                onChange={
                  handleFileSelect
                }
              />


              <textarea
                ref={
                  textareaRef
                }
                value={input}
                onChange={(
                  event
                ) =>
                  setInput(
                    event.target
                      .value
                  )
                }
                onKeyDown={
                  handleKeyDown
                }
                placeholder="Сообщение..."
                rows={1}
                disabled={
                  isLoading
                }
              />


              {input.trim() ? (

                <button
                  type="button"
                  className="icon-button send-button"
                  onClick={() =>
                    sendMessage()
                  }
                  disabled={
                    isLoading
                  }
                  aria-label="Отправить"
                >
                  <SendIcon />
                </button>

              ) : (

                <button
                  type="button"
                  className="icon-button mic-button"
                  onClick={
                    startRecording
                  }
                  disabled={
                    isLoading
                  }
                  aria-label="Записать аудио"
                >
                  <MicIcon />
                </button>

              )}

            </>
          )}


          {/* ==================================================
              RECORDING
              ================================================== */}

          {isRecording && (

            <div className="recording-container">

              <button
                type="button"
                className="recording-action recording-cancel"
                onClick={
                  cancelRecording
                }
                aria-label="Отменить запись"
              >
                <CloseIcon />
              </button>


              <div className="recording-info">

                <div className="recording-dot" />

                <span className="recording-time">
                  {formatRecordingTime(
                    recordingTime
                  )}
                </span>

                <span className="recording-label">
                  Запись...
                </span>

              </div>


              <button
                type="button"
                className="recording-action recording-send"
                onClick={
                  finishRecording
                }
                aria-label="Отправить аудио"
              >
                <CheckIcon />
              </button>

            </div>
          )}

        </div>
      </div>


      {/* ======================================================
          LIGHTBOX
          ====================================================== */}

      {lightboxSrc && (

        <div
          className="lightbox"
          onClick={() =>
            setLightboxSrc(
              null
            )
          }
        >

          <button
            type="button"
            className="lightbox-close"
            onClick={() =>
              setLightboxSrc(
                null
              )
            }
            aria-label="Закрыть"
          >
            <CloseIcon />
          </button>


          <img
            src={lightboxSrc}
            alt="Preview"
            onClick={(
              event
            ) =>
              event.stopPropagation()
            }
          />

        </div>
      )}

    </div>
  );
}
