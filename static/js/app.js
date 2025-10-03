// CxKitty Web UI - JavaScript Application Logic

class CxKittyApp {
    constructor() {
        this.socket = null;
        this.currentUser = null;
        this.selectedCourses = new Set();
        this.currentTaskId = null;
        this.qrCheckInterval = null;
        
        this.init();
    }

    init() {
        this.initSocketIO();
        this.initEventListeners();
        this.loadSessions();
    }

    // Socket.IO 初始化
    initSocketIO() {
        // 检查 Socket.IO 是否加载
        if (typeof io === 'undefined') {
            console.warn('Socket.IO 未加载，实时功能将不可用');
            this.socket = null;
            return;
        }
        
        this.socket = io();
        
        this.socket.on('connected', (data) => {
            console.log('WebSocket连接成功:', data);
        });

        this.socket.on('task_event', (data) => {
            this.handleTaskEvent(data);
        });
    }

    // 初始化事件监听
    initEventListeners() {
        // 导航切换
        document.querySelectorAll('.nav-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = link.dataset.page;
                this.switchPage(page);
            });
        });

        // 登录标签切换
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                this.switchTab(tab);
            });
        });

        // 密码登录
        document.getElementById('login-password-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.loginWithPassword();
        });

        // 二维码登录
        document.getElementById('btn-generate-qr').addEventListener('click', () => {
            this.generateQRCode();
        });

        // 退出登录
        document.querySelector('.btn-logout')?.addEventListener('click', () => {
            this.logout();
        });

        // 开始任务
        document.getElementById('btn-start-tasks')?.addEventListener('click', () => {
            this.startTasks();
        });

        // 停止任务
        document.getElementById('btn-stop-task')?.addEventListener('click', () => {
            this.stopTask();
        });

        // 保存配置
        document.getElementById('btn-save-config')?.addEventListener('click', () => {
            this.saveConfig();
        });
    }

    // 切换页面
    switchPage(pageName) {
        document.querySelectorAll('.page').forEach(page => {
            page.classList.remove('active');
        });
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.remove('active');
        });

        document.querySelector(`.page-${pageName}`).classList.add('active');
        document.querySelector(`.nav-link[data-page="${pageName}"]`).classList.add('active');

        // 加载页面数据
        if (pageName === 'courses' && this.currentUser) {
            this.loadCourses();
        } else if (pageName === 'config') {
            this.loadConfig();
        }
    }

    // 切换登录标签
    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });

        document.querySelector(`.tab-btn[data-tab="${tabName}"]`).classList.add('active');
        document.getElementById(`tab-${tabName}`).classList.add('active');
    }

    // 加载会话列表
    async loadSessions() {
        try {
            const response = await fetch('/api/sessions');
            const data = await response.json();
            
            const sessionList = document.getElementById('session-list');
            
            if (data.sessions.length === 0) {
                sessionList.innerHTML = '<p class="loading-text">暂无保存的会话</p>';
                return;
            }

            sessionList.innerHTML = data.sessions.map(session => `
                <div class="session-item" data-puid="${session.puid}">
                    <div class="session-info">
                        <div class="session-name">${session.name}</div>
                        <div class="session-meta">
                            手机号: ${session.phone} | PUID: ${session.puid}
                        </div>
                    </div>
                </div>
            `).join('');

            // 添加点击事件
            sessionList.querySelectorAll('.session-item').forEach(item => {
                item.addEventListener('click', () => {
                    const puid = parseInt(item.dataset.puid);
                    this.loginWithSession(puid);
                });
            });
        } catch (error) {
            console.error('加载会话失败:', error);
            this.showToast('加载会话失败', 'error');
        }
    }

    // 密码登录
    async loginWithPassword() {
        const form = document.getElementById('login-password-form');
        const formData = new FormData(form);
        const data = {
            phone: formData.get('phone'),
            password: formData.get('password')
        };

        try {
            const response = await fetch('/api/login/password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (result.success) {
                this.currentUser = result.account;
                this.onLoginSuccess();
            } else {
                this.showToast(result.message || '登录失败', 'error');
            }
        } catch (error) {
            console.error('登录失败:', error);
            this.showToast('网络错误，请重试', 'error');
        }
    }

    // 二维码登录
    async generateQRCode() {
        try {
            const response = await fetch('/api/login/qr/init', {
                method: 'POST'
            });

            const result = await response.json();

            if (result.success) {
                const qrImage = document.getElementById('qrcode-image');
                const qrStatus = document.getElementById('qrcode-status-text');
                const qrStatusContainer = document.querySelector('.qrcode-status');

                qrImage.src = result.qr_image;
                qrStatus.textContent = '请使用学习通扫描二维码';
                qrStatusContainer.classList.add('hide');

                // 开始轮询检查状态
                this.startQRCodeCheck();
            }
        } catch (error) {
            console.error('生成二维码失败:', error);
            this.showToast('生成二维码失败', 'error');
        }
    }

    // 轮询检查二维码状态
    startQRCodeCheck() {
        if (this.qrCheckInterval) {
            clearInterval(this.qrCheckInterval);
        }

        this.qrCheckInterval = setInterval(async () => {
            try {
                const response = await fetch('/api/login/qr/check', {
                    method: 'POST'
                });

                const result = await response.json();
                const qrStatus = document.getElementById('qrcode-status-text');
                const qrStatusContainer = document.querySelector('.qrcode-status');

                if (result.status === 'success') {
                    clearInterval(this.qrCheckInterval);
                    this.currentUser = result.account;
                    this.onLoginSuccess();
                } else if (result.status === 'scanned') {
                    qrStatus.textContent = `已扫描，等待确认: ${result.nickname}`;
                    qrStatusContainer.classList.remove('hide');
                } else if (result.status === 'expired' || result.status === 'error') {
                    clearInterval(this.qrCheckInterval);
                    qrStatus.textContent = result.message;
                    qrStatusContainer.classList.remove('hide');
                    this.showToast(result.message, 'error');
                }
            } catch (error) {
                console.error('检查二维码状态失败:', error);
            }
        }, 2000);
    }

    // 会话登录
    async loginWithSession(puid) {
        try {
            const response = await fetch('/api/login/session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ puid })
            });

            const result = await response.json();

            if (result.success) {
                this.currentUser = result.account;
                this.onLoginSuccess();
            } else {
                this.showToast(result.message || '登录失败', 'error');
            }
        } catch (error) {
            console.error('会话登录失败:', error);
            this.showToast('网络错误，请重试', 'error');
        }
    }

    // 登录成功处理
    onLoginSuccess() {
        this.showToast('登录成功', 'success');
        
        // 更新UI
        document.querySelector('.user-name').textContent = this.currentUser.name;
        document.querySelector('.user-info').style.display = 'flex';
        document.querySelectorAll('.nav-link[data-page="courses"], .nav-link[data-page="tasks"]')
            .forEach(link => link.style.display = 'block');

        // 切换到课程页面
        this.switchPage('courses');
    }

    // 退出登录
    logout() {
        this.currentUser = null;
        this.selectedCourses.clear();
        
        document.querySelector('.user-info').style.display = 'none';
        document.querySelectorAll('.nav-link[data-page="courses"], .nav-link[data-page="tasks"]')
            .forEach(link => link.style.display = 'none');
        
        this.switchPage('login');
        this.showToast('已退出登录', 'success');
    }

    // 加载课程列表
    async loadCourses() {
        const coursesGrid = document.getElementById('courses-grid');
        coursesGrid.innerHTML = '<p class="loading-text">加载中...</p>';

        try {
            const response = await fetch('/api/classes');
            const result = await response.json();

            if (result.success) {
                coursesGrid.innerHTML = result.classes.map(course => `
                    <div class="course-card" data-index="${course.index}">
                        <img class="course-image" src="${course.image || ''}" 
                             onerror="this.style.display='none'" alt="${course.name}">
                        <div class="course-body">
                            <div class="course-name">${course.name}</div>
                            <div class="course-meta">
                                <div>教师: ${course.teacher}</div>
                                <div>课程ID: ${course.course_id}</div>
                            </div>
                            <span class="course-status ${course.status === '进行中' ? 'ongoing' : 'finished'}">
                                ${course.status}
                            </span>
                        </div>
                    </div>
                `).join('');

                // 添加点击事件
                coursesGrid.querySelectorAll('.course-card').forEach(card => {
                    card.addEventListener('click', () => {
                        const index = parseInt(card.dataset.index);
                        if (this.selectedCourses.has(index)) {
                            this.selectedCourses.delete(index);
                            card.classList.remove('selected');
                        } else {
                            this.selectedCourses.add(index);
                            card.classList.add('selected');
                        }
                    });
                });
            } else {
                coursesGrid.innerHTML = '<p class="loading-text">加载失败，请重试</p>';
            }
        } catch (error) {
            console.error('加载课程失败:', error);
            coursesGrid.innerHTML = '<p class="loading-text">网络错误，请重试</p>';
        }
    }

    // 开始任务
    async startTasks() {
        if (this.selectedCourses.size === 0) {
            this.showToast('请至少选择一门课程', 'warning');
            return;
        }

        const classIndices = Array.from(this.selectedCourses);

        try {
            const response = await fetch('/api/task/start', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ class_indices: classIndices })
            });

            const result = await response.json();

            if (result.success) {
                this.currentTaskId = result.task_id;
                this.switchPage('tasks');
                this.showToast('任务已开始', 'success');
            } else {
                this.showToast(result.message || '启动任务失败', 'error');
            }
        } catch (error) {
            console.error('启动任务失败:', error);
            this.showToast('网络错误，请重试', 'error');
        }
    }

    // 停止任务
    stopTask() {
        if (this.currentTaskId) {
            this.showToast('任务已停止', 'warning');
            this.currentTaskId = null;
        }
    }

    // 处理任务事件
    handleTaskEvent(data) {
        if (!this.socket) {
            console.warn('Socket未初始化，无法处理事件');
            return;
        }
        
        if (data.task_id !== this.currentTaskId) {
            return;
        }

        const logContent = document.getElementById('log-content');
        const progressText = document.getElementById('progress-text');
        const progressFill = document.getElementById('progress-fill');

        // 处理特殊事件类型
        switch (data.type) {
            case 'video_progress':
                this.handleVideoProgress(data);
                return;
            case 'video_report':
                this.handleVideoReport(data);
                return;
            case 'question_progress':
                this.handleQuestionProgress(data);
                return;
            case 'question_submit':
                this.handleQuestionSubmit(data);
                return;
        }

        // 添加日志条目
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry';
        
        switch (data.type) {
            case 'chapter_start':
            case 'task_point_start':
                logEntry.classList.add('info');
                break;
            case 'chapter_complete':
            case 'task_point_complete':
            case 'complete':
                logEntry.classList.add('success');
                break;
            case 'error':
            case 'captcha_failed':
                logEntry.classList.add('error');
                break;
            case 'chapter_locked':
            case 'captcha':
                logEntry.classList.add('warning');
                break;
            default:
                logEntry.classList.add('info');
        }

        const timestamp = new Date().toLocaleTimeString();
        logEntry.textContent = `[${timestamp}] ${data.message}`;
        logContent.appendChild(logEntry);
        logContent.scrollTop = logContent.scrollHeight;

        // 更新进度文本
        progressText.textContent = data.message;

        // 如果任务完成
        if (data.type === 'complete') {
            progressFill.style.width = '100%';
            this.showToast('任务执行完成', 'success');
            this.currentTaskId = null;
            // 隐藏进度显示
            document.getElementById('video-progress-container').style.display = 'none';
            document.getElementById('question-progress-container').style.display = 'none';
        }
    }

    // 处理视频播放进度
    handleVideoProgress(data) {
        const container = document.getElementById('video-progress-container');
        container.style.display = 'block';
        
        const videoData = data.data;
        document.getElementById('video-title').textContent = videoData.title;
        document.getElementById('video-progress-fill').style.width = videoData.progress_percent + '%';
        
        // 格式化时间
        const formatTime = (seconds) => {
            const min = Math.floor(seconds / 60);
            const sec = seconds % 60;
            return `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
        };
        
        document.getElementById('video-current-time').textContent = formatTime(videoData.current_time);
        document.getElementById('video-duration').textContent = formatTime(videoData.duration);
        document.getElementById('video-speed').textContent = `x${videoData.speed}`;
        document.getElementById('video-report-timer').textContent = `${videoData.next_report}s后上报`;
    }

    // 处理视频上报事件
    handleVideoReport(data) {
        const logContent = document.getElementById('log-content');
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry ' + (data.data.is_success ? 'success' : 'error');
        
        const timestamp = new Date().toLocaleTimeString();
        logEntry.textContent = `[${timestamp}] ${data.message}`;
        logContent.appendChild(logEntry);
        logContent.scrollTop = logContent.scrollHeight;
    }

    // 处理答题进度
    handleQuestionProgress(data) {
        const container = document.getElementById('question-progress-container');
        container.style.display = 'block';
        
        const qData = data.data;
        document.getElementById('question-total').textContent = qData.total;
        document.getElementById('question-completed').textContent = qData.completed;
        document.getElementById('question-failed').textContent = qData.incompleted;
        
        const question = qData.question;
        const currentQuestion = document.getElementById('current-question');
        currentQuestion.innerHTML = `
            <div class="question-info">
                <span class="question-type">${question.type}</span>
                <span class="question-status ${qData.answer_status ? 'status-success' : 'status-failed'}">
                    ${qData.answer_status ? '✓ 已匹配' : '✗ 未匹配'}
                </span>
            </div>
            <div class="question-text">${question.value}</div>
            <div class="question-answer">答案: ${question.answer}</div>
        `;
    }

    // 处理答题提交事件
    handleQuestionSubmit(data) {
        const logContent = document.getElementById('log-content');
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry ' + (data.data.is_success ? 'success' : 'error');
        
        const timestamp = new Date().toLocaleTimeString();
        logEntry.textContent = `[${timestamp}] ${data.message}`;
        logContent.appendChild(logEntry);
        logContent.scrollTop = logContent.scrollHeight;
    }

    // 加载配置
    async loadConfig() {
        try {
            const response = await fetch('/api/config');
            const result = await response.json();

            if (result.success) {
                const config = result.config;
                
                document.getElementById('config-video-enable').checked = config.video.enable;
                document.getElementById('config-video-wait').value = config.video.wait;
                
                document.getElementById('config-work-enable').checked = config.work.enable;
                document.getElementById('config-work-wait').value = config.work.wait;
                document.getElementById('config-work-fuzzer').checked = config.work.fallback_fuzzer;
                
                document.getElementById('config-document-enable').checked = config.document.enable;
                document.getElementById('config-document-wait').value = config.document.wait;
                
                document.getElementById('config-exam-confirm').checked = config.exam.confirm_submit;
                document.getElementById('config-exam-fuzzer').checked = config.exam.fallback_fuzzer;
            }
        } catch (error) {
            console.error('加载配置失败:', error);
        }
    }

    // 保存配置
    saveConfig() {
        // Note: 这是前端配置，实际的配置保存需要后端支持
        // 目前仅作为UI展示
        this.showToast('配置保存功能需要后端实现', 'warning');
    }

    // 显示提示消息
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;

        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => {
                container.removeChild(toast);
            }, 300);
        }, 3000);
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.app = new CxKittyApp();
});
