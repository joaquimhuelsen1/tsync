// Elementos da UI
const connectBtn = document.getElementById('connect-btn');
const disconnectBtn = document.getElementById('disconnect-btn');
const userInfo = document.getElementById('user-info');
const connectionStatus = document.getElementById('connection-status');
const currentSessionElement = document.getElementById('current-session');
const logsContainer = document.getElementById('logs-container');
const clearLogsBtn = document.getElementById('clear-logs-btn');
const autoClearToggle = document.getElementById('auto-clear-toggle');
const clearIntervalInput = document.getElementById('clear-interval');
const manageSessionsBtn = document.getElementById('manage-sessions-btn');
const newSessionBtn = document.getElementById('new-session-btn');

// Elementos para envio de mensagens
const refreshChatsBtn = document.getElementById('refresh-chats-btn');
const chatSelect = document.getElementById('chat-select');
const messageText = document.getElementById('message-text');
const sendMessageBtn = document.getElementById('send-message-btn');
const copyGroupIdBtn = document.getElementById('copy-group-id-btn');

// Elementos dos modais
const modalOverlay = document.getElementById('modal-overlay');
const connectModal = document.getElementById('connect-modal');
const manageSessionsModal = document.getElementById('manage-sessions-modal');
const sessionsList = document.getElementById('sessions-list');
const sessionNameInput = document.getElementById('session-name');
const connectSessionBtn = document.getElementById('connect-session-btn');
const closeButtons = document.querySelectorAll('.close');

// Novos elementos da UI
const connectStatus = document.getElementById('connect-status');
const phoneGroup = document.getElementById('phone-group');
const phoneInput = document.getElementById('phone-input');
const codeGroup = document.getElementById('code-group');
const codeInput = document.getElementById('code-input');
const submitCodeBtn = document.getElementById('submit-code-btn');
const passwordGroup = document.getElementById('password-group');
const passwordInput = document.getElementById('password-input');
const submitPasswordBtn = document.getElementById('submit-password-btn');

// Elementos para ID fixo e botão de atualizar
const reconquestMapInfoDisplay = document.getElementById('reconquest-map-info-display');
const reconquestMapIdSpan = document.getElementById('reconquest-map-id-span');

// Configuração do Socket.IO
const socket = io();

// Estado da aplicação
let isConnected = false;
let autoClearEnabled = true;
let autoClearInterval = 5; // minutos
let currentSession = null;
let availableSessions = [];
let reconquestMapId = null; // ID do grupo Reconquest Map

// Inicialização
document.addEventListener('DOMContentLoaded', async () => {
    await fetchStatus();
    await fetchLogs();
    await fetchSessions();
    
    // Configurar eventos de botões
    connectBtn.addEventListener('click', showConnectModal);
    disconnectBtn.addEventListener('click', handleDisconnectClick);
    clearLogsBtn.addEventListener('click', handleClearLogsClick);
    autoClearToggle.addEventListener('change', toggleAutoClear);
    clearIntervalInput.addEventListener('change', updateClearInterval);
    manageSessionsBtn.addEventListener('click', showManageSessionsModal);
    newSessionBtn.addEventListener('click', showConnectModal);
    connectSessionBtn.addEventListener('click', connectWithSession);
    submitCodeBtn.addEventListener('click', submitCode);
    submitPasswordBtn.addEventListener('click', submitPassword);
    refreshChatsBtn.addEventListener('click', fetchChats);
    
    if (copyGroupIdBtn) { copyGroupIdBtn.addEventListener('click', copyReconquestMapId); }
    
    closeButtons.forEach(button => { button.addEventListener('click', closeModals); });
    modalOverlay.addEventListener('click', closeModals);
    
    setupSocketEvents();
});

// Função para mostrar/esconder loading
let loadingIndicator = null;
function showLoading(message = 'Processando...') {
    if (!loadingIndicator) {
        loadingIndicator = document.createElement('div');
        loadingIndicator.id = 'loading-indicator';
        loadingIndicator.style.position = 'fixed';
        loadingIndicator.style.top = '50%';
        loadingIndicator.style.left = '50%';
        loadingIndicator.style.transform = 'translate(-50%, -50%)';
        loadingIndicator.style.backgroundColor = 'rgba(0, 0, 0, 0.7)';
        loadingIndicator.style.color = 'white';
        loadingIndicator.style.padding = '20px';
        loadingIndicator.style.borderRadius = '8px';
        loadingIndicator.style.zIndex = '1000';
        loadingIndicator.style.textAlign = 'center';
        loadingIndicator.innerHTML = '<div class="spinner"></div><p style="margin-top: 10px;"></p>'; // Adiciona spinner e parágrafo
        document.body.appendChild(loadingIndicator);
    }
    loadingIndicator.querySelector('p').textContent = message;
    loadingIndicator.style.display = 'block';
    // Adicionar uma classe ao container para talvez desabilitar interações
    const container = document.querySelector('.container');
    container.classList.add('busy');
}

function hideLoading() {
    if (loadingIndicator) {
        loadingIndicator.style.display = 'none';
    }
    // Remover a classe do container
    const container = document.querySelector('.container');
    container.classList.remove('busy');
}

// Buscar o status atual da conexão
async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        updateConnectionUI(data.connected, data.user_info);
        
        // Atualizar informações de sessão
        if (data.current_session) {
            currentSession = data.current_session;
            currentSessionElement.textContent = currentSession;
        } else {
            currentSession = null;
            currentSessionElement.textContent = "nenhuma";
        }
        
        // Atualizar configurações de limpeza automática
        if (data.hasOwnProperty('auto_clear_logs')) {
            autoClearEnabled = data.auto_clear_logs;
            autoClearToggle.checked = autoClearEnabled;
        }
        
        if (data.hasOwnProperty('auto_clear_interval')) {
            autoClearInterval = Math.floor(data.auto_clear_interval / 60); // Converter segundos para minutos
            clearIntervalInput.value = autoClearInterval;
        }
        
    } catch (error) {
        console.error('Erro ao obter status:', error);
        addLog(`Erro ao obter status: ${error.message}`, 'error');
    }
}

// Buscar sessões disponíveis
async function fetchSessions() {
    showLoading('Buscando sessões...');
    try {
        const response = await fetch('/api/sessions');
        const data = await response.json();
        
        availableSessions = data.sessions || [];
        
        // Atualizar lista de sessões na UI
        updateSessionsList();
        
    } catch (error) {
        console.error('Erro ao obter sessões:', error);
        addLog(`Erro ao obter sessões: ${error.message}`, 'error');
    } finally {
        hideLoading();
    }
}

// Atualizar a lista de sessões no modal
function updateSessionsList() {
    sessionsList.innerHTML = '';
    
    if (availableSessions.length === 0) {
        sessionsList.innerHTML = '<div class="no-sessions">Nenhuma sessão encontrada</div>';
        return;
    }
    
    availableSessions.forEach(session => {
        const sessionItem = document.createElement('div');
        sessionItem.className = 'session-item';
        
        const isCurrentSession = session === currentSession;
        
        sessionItem.innerHTML = `
            <div class="session-item-name">${session} ${isCurrentSession ? '(atual)' : ''}</div>
            <div class="session-item-actions">
                ${!isConnected || !isCurrentSession ? `<button class="btn btn-sm btn-primary session-connect-btn" data-session="${session}">Conectar</button>` : ''}
                ${!isCurrentSession ? `<button class="btn btn-sm btn-danger session-remove-btn" data-session="${session}">Remover</button>` : ''}
            </div>
        `;
        
        sessionsList.appendChild(sessionItem);
    });
    
    // Adicionar eventos para os botões de conectar e remover
    document.querySelectorAll('.session-connect-btn').forEach(button => {
        button.addEventListener('click', () => {
            const sessionName = button.getAttribute('data-session');
            connectWithSpecificSession(sessionName);
        });
    });
    
    document.querySelectorAll('.session-remove-btn').forEach(button => {
        button.addEventListener('click', () => {
            const sessionName = button.getAttribute('data-session');
            removeSession(sessionName);
        });
    });
}

// Buscar logs existentes
async function fetchLogs() {
    try {
        const response = await fetch('/api/logs');
        const logs = await response.json();
        
        // Limpar logs existentes
        logsContainer.innerHTML = '';
        
        // Adicionar logs obtidos
        logs.forEach(log => {
            addLog(log);
        });
    } catch (error) {
        console.error('Erro ao obter logs:', error);
        addLog(`Erro ao obter logs: ${error.message}`, 'error');
    }
}

// Mostrar modal de conexão (resetar campos extras)
function showConnectModal() {
    // Resetar estado do modal de conexão
    resetConnectModal(); 
    
    // Se foi aberto pelo botão "Nova Conta", adiciona classe para z-index
    if (event && event.target && event.target.id === 'new-session-btn') {
        connectModal.classList.add('on-top');
    }
    
    connectModal.style.display = 'block';
    modalOverlay.style.display = 'block';
    
    // Focar no campo de nome da sessão
    sessionNameInput.focus();
}

// Mostrar modal de gerenciamento de sessões
function showManageSessionsModal() {
    // Atualizar lista de sessões antes de mostrar o modal
    fetchSessions().then(() => {
        manageSessionsModal.style.display = 'block';
        modalOverlay.style.display = 'block';
    });
}

// Fechar todos os modais (resetar modal de conexão)
function closeModals() {
    connectModal.style.display = 'none';
    manageSessionsModal.style.display = 'none';
    modalOverlay.style.display = 'none';
    
    // Remover a classe de z-index se existir
    connectModal.classList.remove('on-top');
    // Resetar campos do modal de conexão ao fechar
    resetConnectModal();
}

// Resetar o estado do modal de conexão
function resetConnectModal() {
    phoneGroup.style.display = 'block'; // Mostrar campo de telefone por padrão
    codeGroup.style.display = 'none';
    passwordGroup.style.display = 'none';
    codeInput.value = '';
    passwordInput.value = '';
    phoneInput.value = ''; // Limpar telefone também
    connectStatus.textContent = '';
    connectStatus.style.display = 'none';
    // Habilitar/desabilitar botões conforme necessário
    connectSessionBtn.disabled = false;
    submitCodeBtn.disabled = false;
    submitPasswordBtn.disabled = false;
    sessionNameInput.disabled = false;
    phoneInput.disabled = false;
}

// Conectar com sessão (inicia o processo)
function connectWithSession() {
    const sessionName = sessionNameInput.value;
    const phoneNumber = phoneInput.value;
    
    if (!sessionName) {
        showConnectStatus('Por favor, forneça um nome para a sessão.', 'error');
        return;
    }
    
    // Desabilitar campos iniciais
    connectSessionBtn.disabled = true;
    sessionNameInput.disabled = true;
    phoneInput.disabled = true;
    
    showConnectStatus('Iniciando conexão...', 'info');
    
    fetch('/api/connect', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_name: sessionName, phone: phoneNumber }),
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Não fechar o modal ainda, esperar por pedidos de código/senha
            showConnectStatus('Conexão iniciada. Aguardando por código/senha se necessário...', 'info');
            // O backend agora controlará a UI via SocketIO (ask_code/ask_password)
        } else {
            showConnectStatus(`Erro ao iniciar conexão: ${data.message}`, 'error');
            // Reabilitar campos em caso de erro inicial
            connectSessionBtn.disabled = false;
            sessionNameInput.disabled = false;
            phoneInput.disabled = false;
        }
    })
    .catch(error => {
        console.error('Erro na requisição /api/connect:', error);
        showConnectStatus(`Erro de rede ao iniciar conexão: ${error.message}`, 'error');
        // Reabilitar campos em caso de erro de rede
        connectSessionBtn.disabled = false;
        sessionNameInput.disabled = false;
        phoneInput.disabled = false;
    });
}

// Enviar código de login para o backend
function submitCode() {
    const code = codeInput.value;
    if (code) {
        showLoading('Enviando código...');
        socket.emit('code_response', { code: code });
        // Desabilitar campo e botão após envio
        codeInput.disabled = true;
        submitCodeBtn.disabled = true;
    } else {
        showConnectStatus('Por favor, digite o código recebido.', 'error');
    }
}

// Enviar senha 2FA para o backend
function submitPassword() {
    const password = passwordInput.value;
    if (password) {
        showLoading('Enviando senha...');
        socket.emit('password_response', { password: password });
        // Desabilitar campo e botão após envio
        passwordInput.disabled = true;
        submitPasswordBtn.disabled = true;
    } else {
        showConnectStatus('Por favor, digite sua senha 2FA.', 'error');
    }
}

// Configurar ouvintes de eventos Socket.IO
function setupSocketEvents() {
    socket.on('connect', () => {
        console.log('Conectado ao servidor via Socket.IO');
        addLog('Conectado ao servidor WebSocket.', 'system');
        // Se reconectar, buscar status atual
        fetchStatus();
        fetchSessions();
    });

    socket.on('disconnect', () => {
        console.log('Desconectado do servidor Socket.IO');
        addLog('Desconectado do servidor WebSocket.', 'error');
        // Atualizar UI para refletir desconexão do socket
        updateConnectionUI(false, null); 
    });

    socket.on('log', (data) => {
        // Garantir que addLog seja chamado com os parâmetros corretos
        if (typeof data === 'object' && data.message) {
            addLog(data.message, data.type || '');
        } else if (typeof data === 'string') {
            addLog(data, ''); // Log simples como string
        } else {
            console.warn('Formato de log inesperado recebido:', data);
        }
    });

    socket.on('status_update', (data) => {
        console.log('Status Update Recebido:', data); // Debug
        const wasConnected = isConnected;
        updateConnectionUI(data.connected, data.user_info);
        
        // Atualizar sessão atual se fornecida
        if (data.hasOwnProperty('session')) {
            const sessionChanged = currentSession !== data.session;
            currentSession = data.session;
            currentSessionElement.textContent = currentSession || "nenhuma";
            if(sessionChanged) fetchSessions(); // Atualiza lista de sessões se a sessão mudou
        }
        
        // Se conectar pela primeira vez ou reconectar, buscar chats
        if (data.connected && !wasConnected) {
             fetchChats();
        }
        // Se desconectar, limpar ID
        if (!data.connected && wasConnected) {
            reconquestMapId = null;
            updateReconquestMapDisplay();
        }
        
        // Se a conexão for bem sucedida, fechar modais
        if (data.connected) {
             showConnectStatus('Conectado com sucesso!', 'info');
             setTimeout(closeModals, 1500); // Fecha após um tempo
        } else if (data.error) {
            // Mostrar erro APENAS se o modal de conexão estiver visível
            if (connectModal.style.display === 'block') { 
                showConnectStatus(`Erro: ${data.error}`, 'error');
                resetConnectModal(); // Resetar para permitir nova tentativa
        } else {
                addLog(`Erro na conexão/status: ${data.error}`, 'error'); // Log normal se modal fechado
            }
        }
    });
    
    socket.on('logs_cleared', (data) => {
        logsContainer.innerHTML = ''; // Limpar visualmente
        if (data && data.message) {
            addLog(data.message, 'system');
        } else {
             addLog('Logs limpos pelo servidor.', 'system');
        }
    });
    
    socket.on('ask_code', () => {
        console.log("Servidor pediu o código de login.");
        showConnectStatus('Por favor, insira o código de login enviado ao seu Telegram.', 'info');
        // Mostrar o campo de código, esconder o de telefone
        phoneGroup.style.display = 'none';
        codeGroup.style.display = 'block';
        passwordGroup.style.display = 'none';
        codeInput.disabled = false;
        submitCodeBtn.disabled = false;
        codeInput.focus();
    });

    socket.on('ask_password', () => {
        console.log("Servidor pediu a senha 2FA.");
        showConnectStatus('Por favor, insira sua senha de autenticação de dois fatores (2FA).', 'info');
        // Mostrar o campo de senha, esconder outros
        phoneGroup.style.display = 'none';
        codeGroup.style.display = 'none';
        passwordGroup.style.display = 'block';
        passwordInput.disabled = false;
        submitPasswordBtn.disabled = false;
        passwordInput.focus();
    });
}

// Função auxiliar para mostrar mensagens no modal de conexão
function showConnectStatus(message, type = 'info') {
    connectStatus.textContent = message;
    connectStatus.className = `connect-status-message ${type}`; // Aplicar classe de estilo
    connectStatus.style.display = 'block';
}

// Atualizar a UI com base no status da conexão
function updateConnectionUI(connected, userData) {
    isConnected = connected;
    
    if (connected) {
        connectionStatus.textContent = 'Conectado';
        connectionStatus.className = 'connection-status connected';
        
        if (userData && userData.first_name) {
            userInfo.textContent = `Usuário: ${userData.first_name} (ID: ${userData.id})`;
        }
        
        connectBtn.disabled = true;
        disconnectBtn.disabled = false;
    } else {
        connectionStatus.textContent = 'Desconectado';
        connectionStatus.className = 'connection-status disconnected';
        userInfo.textContent = 'Desconectado';
        
        connectBtn.disabled = false;
        disconnectBtn.disabled = true;
    }
}

// Adicionar uma entrada de log na UI
function addLog(message, type = '') {
    console.log('Adicionando log:', message, type); // Debug
    
    const logEntry = document.createElement('div');
    logEntry.className = `log-entry ${type}`;
    
    // Se message for um objeto (log recebido via socket)
    if (typeof message === 'object' && message.message) {
        logEntry.textContent = message.message;
        if (message.type) {
            logEntry.className = `log-entry ${message.type.toLowerCase()}`;
        }
    } else {
        // Se message for uma string (log local)
        logEntry.textContent = message;
    }
    
    logsContainer.appendChild(logEntry);
    
    // Rolar para o final
    logsContainer.scrollTop = logsContainer.scrollHeight;
}

// Buscar chats recentes e atualizar o ID fixo
async function fetchChats() {
    if (!isConnected) {
        addLog('Conecte-se primeiro para atualizar os chats.', 'error');
        return;
    }
    
    addLog('Atualizando lista de chats recentes (últimos 7 dias)...', 'info');
    refreshChatsBtn.disabled = true; // Desabilitar botão durante busca
    
    try {
        const response = await fetch('/api/chats');
        const data = await response.json();
        
        if (data.status === 'success') {
            // Atualizar ID fixo global e na UI
                reconquestMapId = data.reconquest_map_id;
            updateReconquestMapDisplay();
            
            // Popular o dropdown (removido, mas manter lógica se voltar)
            /*
            chatSelect.innerHTML = '<option value="">Selecione um chat</option>';
            if (data.chats && data.chats.length > 0) {
            data.chats.forEach(chat => {
                        const option = document.createElement('option');
                        option.value = chat.id;
                    option.textContent = `${chat.name} (${chat.type})`;
                    chatSelect.appendChild(option);
                });
                        } else {
                 chatSelect.innerHTML = '<option value="">Nenhum chat recente encontrado</option>';
            }
            */
            addLog(`Chats recentes atualizados. ID TheReconquestMap: ${reconquestMapId || 'Não encontrado'}.`, 'info');
        } else {
            addLog(`Erro ao atualizar chats: ${data.message}`, 'error');
            updateReconquestMapDisplay(); // Atualiza display mesmo em erro
        }
    } catch (error) {
        console.error('Erro ao buscar chats:', error);
        addLog(`Erro de rede ao buscar chats: ${error.message}`, 'error');
        updateReconquestMapDisplay(); // Atualiza display mesmo em erro
    } finally {
        refreshChatsBtn.disabled = false; // Reabilitar botão
    }
}

// Função para remover uma sessão
async function removeSession(sessionName) {
    if (!confirm(`Tem certeza que deseja remover a sessão "${sessionName}"?`)) {
        return;
    }
    try {
        const response = await fetch('/api/remove-session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_name: sessionName })
        });
        const data = await response.json();
        if (data.status === 'success') {
            addLog(data.message, 'system');
            await fetchSessions(); // Atualiza a lista
            if (sessionName === currentSession) { // Se removeu a atual, reseta
                currentSession = null;
                currentSessionElement.textContent = "nenhuma";
                updateConnectionUI(false, null); // Garante que a UI reflita desconexão
            }
        } else {
            addLog(`Erro ao remover sessão: ${data.message}`, 'error');
        }
    } catch (error) {
        console.error('Erro ao remover sessão:', error);
        addLog(`Erro de rede ao remover sessão: ${error.message}`, 'error');
    }
}

// Funções para toggle/update auto-clear (faltavam no exemplo anterior)
async function toggleAutoClear() { 
    autoClearEnabled = autoClearToggle.checked;
    try {
        await fetch('/api/toggle-auto-clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: autoClearEnabled })
        });
        addLog(`Limpeza automática ${autoClearEnabled ? 'ativada' : 'desativada'}`, 'system');
    } catch (error) {
        console.error('Erro ao alternar limpeza automática:', error);
        addLog(`Erro ao alternar limpeza automática: ${error.message}`, 'error');
    }
}
async function updateClearInterval() { 
    let newInterval = parseInt(clearIntervalInput.value);
    if (isNaN(newInterval) || newInterval < 1) { newInterval = 5; clearIntervalInput.value = newInterval; }
    if (newInterval > 60) { newInterval = 60; clearIntervalInput.value = newInterval; }
    autoClearInterval = newInterval;
    try {
        await fetch('/api/toggle-auto-clear', { // Usa a mesma rota para atualizar o intervalo
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interval: autoClearInterval })
        });
        addLog(`Intervalo de limpeza automática definido para ${autoClearInterval} minutos`, 'system');
    } catch (error) {
        console.error('Erro ao atualizar intervalo:', error);
        addLog(`Erro ao atualizar intervalo: ${error.message}`, 'error');
    }
}

// Conectar com sessão específica (do modal de gerenciamento)
async function connectWithSpecificSession(sessionName) {
    if (!sessionName) return;
    showManageSessionsModal(); // Fecha o modal de gerenciamento
    
    addLog(`Tentando conectar com sessão existente: ${sessionName}...`, 'info');
    
    // Não precisa de número de telefone para sessões existentes
    fetch('/api/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_name: sessionName, phone: null }), // Passa phone como null
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
             addLog(`Conexão com ${sessionName} iniciada.`, 'info');
             // Status será atualizado via SocketIO
        } else {
            addLog(`Erro ao conectar com ${sessionName}: ${data.message}`, 'error');
        }
    })
    .catch(error => {
        console.error(`Erro na requisição /api/connect para ${sessionName}:`, error);
        addLog(`Erro de rede ao conectar com ${sessionName}: ${error.message}`, 'error');
    });
}

function updateReconquestMapDisplay() {
    if (reconquestMapId) {
        reconquestMapIdSpan.textContent = reconquestMapId;
        copyGroupIdBtn.disabled = false;
        reconquestMapInfoDisplay.style.display = 'block';
    } else {
        reconquestMapIdSpan.textContent = 'Não encontrado';
        copyGroupIdBtn.disabled = true;
        // Manter o display visível após a primeira busca para o botão Atualizar
        reconquestMapInfoDisplay.style.display = 'block'; 
    }
}

function copyReconquestMapId() {
    if (reconquestMapId) {
        navigator.clipboard.writeText(reconquestMapId).then(() => {
            addLog('ID do grupo copiado para a área de transferência.', 'info');
        }).catch(err => {
            console.error('Erro ao copiar ID:', err);
            addLog('Erro ao copiar ID do grupo.', 'error');
        });
    }
}

// Função wrapper para lidar com o clique no botão Desconectar
async function handleDisconnectClick() {
    try {
        disconnectBtn.disabled = true; // Desabilitar botão durante a ação
        addLog('Tentando desconectar...', 'system');
        
        const response = await fetch('/api/disconnect', {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.status === 'error') {
             addLog(`Erro ao desconectar: ${data.message}`, 'error');
        } else {
            // O status_update via SocketIO deve atualizar a UI
            addLog(`Solicitação de desconexão enviada: ${data.message}`, 'system');
        }
        
    } catch (error) {
        console.error('Erro na requisição /api/disconnect:', error);
        addLog(`Erro de rede ao desconectar: ${error.message}`, 'error');
    } finally {
        // Reabilitar o botão se a conexão não mudou (pode ter falhado)
        if (isConnected) {
             disconnectBtn.disabled = false;
        }
    }
}

// Função para limpar logs (chamada pelo botão)
async function handleClearLogsClick() {
    try {
        const response = await fetch('/api/clear-logs', {
            method: 'POST'
        });
        const data = await response.json();
        // A confirmação visual vem via evento 'logs_cleared' do socket
        if (data.status === 'success') {
             addLog('Solicitação para limpar logs enviada.', 'system');
    } else {
             addLog(`Erro ao solicitar limpeza de logs: ${data.message}`, 'error');
        }
    } catch (error) {
        console.error('Erro ao limpar logs:', error);
        addLog(`Erro de rede ao limpar logs: ${error.message}`, 'error');
    }
} 