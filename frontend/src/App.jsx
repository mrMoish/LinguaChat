  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    // Создаем только одно сообщение пользователя, без истории
    const userMessage = { role: 'user', content: input };
    // Обратите внимание: вместо [...messages, userMessage] мы берем [userMessage]
    setMessages([userMessage]); 
    setInput('');
    setIsLoading(true);

    try {
      const response = await fetch(`/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: input
          // поле history больше не отправляем
        }),
      });
      // ... остальной код без изменений ...
