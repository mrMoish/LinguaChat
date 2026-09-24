import { useEffect, useState } from 'react';

const API_URL = import.meta.env.VITE_API_URL;

export default function Admin() {
  const [secret, setSecret] = useState(
    () => sessionStorage.getItem('admin_secret') || ''
  );

  const [authenticated, setAuthenticated] = useState(
    () => Boolean(sessionStorage.getItem('admin_secret'))
  );

  const [users, setUsers] = useState([]);
  const [totalUsers, setTotalUsers] = useState(0);

  const [page, setPage] = useState(1);
  const limit = 20;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [selectedUser, setSelectedUser] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const totalPages = Math.max(
    1,
    Math.ceil(totalUsers / limit)
  );

  async function loadUsers(currentSecret = secret) {
    if (!currentSecret) {
      return false;
    }

    setLoading(true);
    setError('');

    try {
      const response = await fetch(
        `${API_URL}/api/admin/users?page=${page}&limit=${limit}`,
        {
          headers: {
            Authorization: `Bearer ${currentSecret}`,
          },
        }
      );

      if (response.status === 401) {
        sessionStorage.removeItem('admin_secret');
        setSecret('');
        setAuthenticated(false);
        setUsers([]);
        setTotalUsers(0);
        throw new Error('Неверный пароль');
      }

      if (!response.ok) {
        throw new Error(
          `Ошибка сервера: ${response.status}`
        );
      }

      const data = await response.json();

      setUsers(data.users);
      setTotalUsers(data.total_users);

      return true;
    } catch (error) {
      setError(error.message);
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function login(event) {
    event.preventDefault();

    if (!secret.trim()) {
      setError('Введите пароль');
      return;
    }

    setError('');

    const success = await loadUsers(secret);

    if (success) {
      sessionStorage.setItem(
        'admin_secret',
        secret
      );

      setAuthenticated(true);
      setPage(1);
    }
  }

  function logout() {
    sessionStorage.removeItem('admin_secret');

    setSecret('');
    setAuthenticated(false);

    setUsers([]);
    setTotalUsers(0);

    setSelectedUser(null);
    setHistory([]);

    setPage(1);
    setError('');
  }

  async function openUser(user) {
    setSelectedUser(user);
    setHistory([]);
    setHistoryLoading(true);
    setError('');

    try {
      const response = await fetch(
        `${API_URL}/api/admin/users/${encodeURIComponent(
          user.session_id
        )}/history`,
        {
          headers: {
            Authorization: `Bearer ${secret}`,
          },
        }
      );

      if (response.status === 401) {
        logout();
        throw new Error('Сессия администратора истекла');
      }

      if (!response.ok) {
        throw new Error(
          `Ошибка сервера: ${response.status}`
        );
      }

      const data = await response.json();

      setHistory(data.messages);
    } catch (error) {
      setError(error.message);
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    if (!authenticated) {
      return;
    }

    loadUsers();
  }, [authenticated, page]);

  if (!authenticated) {
    return (
      <div style={styles.loginContainer}>
        <form
          onSubmit={login}
          style={styles.loginForm}
        >
          <h1>Admin</h1>

          <input
            type="password"
            placeholder="Admin secret"
            value={secret}
            onChange={(event) =>
              setSecret(event.target.value)
            }
            style={styles.input}
            autoFocus
          />

          <button
            type="submit"
            style={styles.button}
            disabled={loading}
          >
            {loading ? 'Проверка...' : 'Войти'}
          </button>

          {error && (
            <div style={styles.error}>
              {error}
            </div>
          )}
        </form>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <div>
          <h1>Users</h1>

          <div style={styles.total}>
            Всего пользователей:{' '}
            <b>{totalUsers}</b>
          </div>
        </div>

        <button
          onClick={logout}
          style={styles.logoutButton}
        >
          Выйти
        </button>
      </header>

      {error && (
        <div style={styles.error}>
          {error}
        </div>
      )}

      {loading ? (
        <div>Загрузка...</div>
      ) : (
        <>
          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th>Session ID</th>
                  <th>Сообщений</th>
                  <th>Последнее сообщение</th>
                  <th>Дата</th>
                </tr>
              </thead>

              <tbody>
                {users.length === 0 ? (
                  <tr>
                    <td
                      colSpan="4"
                      style={styles.empty}
                    >
                      Пользователей пока нет
                    </td>
                  </tr>
                ) : (
                  users.map((user) => (
                    <tr
                      key={user.session_id}
                      onClick={() =>
                        openUser(user)
                      }
                      style={styles.row}
                    >
                      <td style={styles.sessionId}>
                        {user.session_id}
                      </td>

                      <td>
                        {user.message_count}
                      </td>

                      <td
                        style={
                          styles.lastMessage
                        }
                      >
                        {user.last_user_message ||
                          '—'}
                      </td>

                      <td>
                        {user.last_user_message_at
                          ? new Date(
                              user.last_user_message_at
                            ).toLocaleString()
                          : '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div style={styles.pagination}>
            <button
              disabled={page <= 1}
              onClick={() =>
                setPage((p) => p - 1)
              }
            >
              ← Назад
            </button>

            <span>
              Страница {page} из {totalPages}
            </span>

            <button
              disabled={page >= totalPages}
              onClick={() =>
                setPage((p) => p + 1)
              }
            >
              Вперёд →
            </button>
          </div>
        </>
      )}

      {selectedUser && (
        <div style={styles.modal}>
          <div style={styles.modalContent}>
            <div style={styles.modalHeader}>
              <div>
                <h2>
                  История пользователя
                </h2>

                <div style={styles.sessionId}>
                  {selectedUser.session_id}
                </div>
              </div>

              <button
                onClick={() =>
                  setSelectedUser(null)
                }
                style={styles.closeButton}
              >
                ✕
              </button>
            </div>

            {historyLoading ? (
              <div>
                Загрузка истории...
              </div>
            ) : history.length === 0 ? (
              <div>
                История сообщений пуста
              </div>
            ) : (
              <div style={styles.history}>
                {history.map((message) => (
                  <div
                    key={message.id}
                    style={{
                      ...styles.message,
                      ...(message.role === 'user'
                        ? styles.userMessage
                        : styles.assistantMessage),
                    }}
                  >
                    <div style={styles.role}>
                      {message.role === 'user'
                        ? 'User'
                        : 'Assistant'}
                    </div>

                    {message.content && (
                      <div
                        style={
                          styles.messageContent
                        }
                      >
                        {message.content}
                      </div>
                    )}

                    {message.media_url && (
                      <div
                        style={
                          styles.mediaContainer
                        }
                      >
                        {message.message_type ===
                          'image' && (
                          <img
                            src={
                              message.media_url
                            }
                            alt="User media"
                            style={styles.image}
                          />
                        )}

                        {message.message_type !==
                          'image' && (
                          <a
                            href={
                              message.media_url
                            }
                            target="_blank"
                            rel="noreferrer"
                          >
                            Открыть media
                          </a>
                        )}
                      </div>
                    )}

                    <div
                      style={styles.messageDate}
                    >
                      {new Date(
                        message.created_at
                      ).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    padding: '30px',
    fontFamily:
      'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    background: '#f7f7f7',
  },

  loginContainer: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#f7f7f7',
    fontFamily:
      'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },

  loginForm: {
    width: '300px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    padding: '30px',
    background: 'white',
    borderRadius: '12px',
    boxShadow:
      '0 4px 20px rgba(0, 0, 0, 0.08)',
  },

  input: {
    padding: '12px',
    fontSize: '16px',
    border: '1px solid #ccc',
    borderRadius: '6px',
  },

  button: {
    padding: '12px',
    cursor: 'pointer',
    border: 'none',
    borderRadius: '6px',
    background: '#111',
    color: 'white',
    fontSize: '15px',
  },

  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '30px',
  },

  total: {
    color: '#666',
  },

  logoutButton: {
    padding: '8px 14px',
    cursor: 'pointer',
    border: '1px solid #ccc',
    borderRadius: '6px',
    background: 'white',
  },

  error: {
    padding: '12px',
    marginBottom: '20px',
    background: '#ffe5e5',
    color: '#b00020',
    borderRadius: '6px',
  },

  tableWrapper: {
    overflowX: 'auto',
    background: 'white',
    borderRadius: '10px',
    boxShadow:
      '0 2px 10px rgba(0, 0, 0, 0.05)',
  },

  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },

  row: {
    borderBottom: '1px solid #ddd',
    cursor: 'pointer',
  },

  sessionId: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#666',
  },

  lastMessage: {
    maxWidth: '400px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  empty: {
    padding: '30px',
    textAlign: 'center',
    color: '#777',
  },

  pagination: {
    display: 'flex',
    gap: '20px',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: '25px',
  },

  modal: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.5)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    padding: '20px',
    zIndex: 1000,
  },

  modalContent: {
    background: 'white',
    width: '100%',
    maxWidth: '800px',
    maxHeight: '90vh',
    overflow: 'auto',
    borderRadius: '12px',
    padding: '20px',
  },

  modalHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: '20px',
  },

  closeButton: {
    cursor: 'pointer',
    border: 'none',
    background: 'transparent',
    fontSize: '20px',
  },

  history: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },

  message: {
    padding: '12px',
    borderRadius: '8px',
  },

  userMessage: {
    background: '#e8f0ff',
  },

  assistantMessage: {
    background: '#f3f3f3',
  },

  role: {
    fontSize: '12px',
    fontWeight: 'bold',
    marginBottom: '5px',
  },

  messageContent: {
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
  },

  mediaContainer: {
    marginTop: '10px',
  },

  image: {
    maxWidth: '300px',
    maxHeight: '300px',
    borderRadius: '8px',
    objectFit: 'contain',
  },

  messageDate: {
    marginTop: '8px',
    fontSize: '11px',
    color: '#777',
  },
};