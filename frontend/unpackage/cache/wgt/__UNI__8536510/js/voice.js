// ============================================
// AI 语音交互引擎 (Voice Engine)
// 包含: TTS 真实自然语音朗读、STT 语音识别输入、快捷开关与全局偏好管理
// 跨端适配: PC浏览器 / 手机浏览器 / HBuilderX 原生 App
// ============================================

(function() {
    class VoiceEngine {
        constructor() {
            this.synth = window.speechSynthesis || null;
            this.recognition = null;
            this.isRecording = false;
            this.currentAudio = null;
            this.currentUtterance = null;
            this.currentPlayingEl = null;

            // 初始化设置
            this.settings = this.loadSettings();

            // 初始化语音识别 (STT)
            this.initSpeechRecognition();
        }

        loadSettings() {
            try {
                const saved = localStorage.getItem('VOICE_SETTINGS');
                if (saved) {
                    return JSON.parse(saved);
                }
            } catch (e) {
                console.warn('读取语音设置失败:', e);
            }
            return {
                autoRead: false,          // 默认关闭自动播报（防打扰）
                persona: 'male',          // 'male' (儒雅男声-云希) | 'female' (亲切女声-晓晓)
                rate: 1.0,                // 语速: 0.8 / 1.0 / 1.2
                micEnabled: true          // 允许麦克风语音输入
            };
        }

        saveSettings(newSettings) {
            this.settings = { ...this.settings, ...newSettings };
            try {
                localStorage.setItem('VOICE_SETTINGS', JSON.stringify(this.settings));
            } catch (e) {}
            this.updateHeaderToggleBtn();
        }

        // 初始化浏览器原生语音识别 (Web Speech API)
        initSpeechRecognition() {
            const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition || null;
            if (!SpeechRec) {
                return;
            }
            try {
                this.recognition = new SpeechRec();
                this.recognition.lang = 'zh-CN';
                this.recognition.continuous = false;
                this.recognition.interimResults = true;
            } catch (e) {
                console.warn('初始化语音识别器异常:', e);
            }
        }

        // 深度清理文本中的特殊字符、Emoji、Markdown 和评分格式，生成最自然纯净的活人发音文本
        cleanTextForSpeech(text) {
            if (!text) return '';
            let cleaned = text;

            // 1. 去除所有 Emoji 图标 (⭐, 🔄, 📊, 📝, 🎙️, 📋, 🔍, 💡, ✅, ❌, ⚠️, 💬, 👤, ⚙️, 🏠, 🎉, 🤔, 📄, 📌 等)
            cleaned = cleaned.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F1E6}-\u{1F1FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}]/gu, '');
            cleaned = cleaned.replace(/[⭐🔄📊📝🎙️📋🔍💡✅❌⚠️💬👤⚙️🏠🎉🤔📄📌]/g, '');

            // 2. 去除分类标签如 [技术基础]、[项目深挖]、[系统设计]、[行为表现]、[综合]
            cleaned = cleaned.replace(/\[(?:技术基础|项目深挖|系统设计|行为表现|综合|项目经历|编程能力|架构设计|考点:[^\]]+)\]/g, '');

            // 3. 将 "第 1/12 题" 或 "第 1 题" 转化为自然的 "第1题，"
            cleaned = cleaned.replace(/第\s*(\d+)\s*\/\s*\d+\s*题/g, '第 $1 题，');
            // 将 "已答 0/12 题" 转化为 "已答 0 题"
            cleaned = cleaned.replace(/已答\s*(\d+)\s*\/\s*\d+\s*题/g, '已答 $1 题');
            // 将 "评分: 8/10" 转化为 "评分 8 分"
            cleaned = cleaned.replace(/评分[:：]\s*(\d+)\s*\/\s*\d+/g, '评分 $1 分');

            // 4. 去除 Markdown 格式标记
            cleaned = cleaned
                .replace(/\*\*|__/g, '')             // 去除加粗
                .replace(/^#+\s*/gm, '')             // 去除各级标题
                .replace(/`{1,3}[^`]*`{1,3}/g, '')   // 去除代码块
                .replace(/[`*~_]/g, '')              // 去除行内标记
                .replace(/\[(.*?)\]\(.*?\)/g, '$1')  // 超链接只保留文本
                .replace(/^[-\d.]+\s*/gm, '')        // 去除列表序号
                .replace(/^---\s*$/gm, '')           // 去除分割线
                .replace(/[-=]{3,}/g, '');           // 去除横线

            // 5. 标点与换行优化：换行转为自然逗号停顿，合并多余标点
            cleaned = cleaned
                .replace(/[\r\n]+/g, '，')
                .replace(/，{2,}/g, '，')
                .replace(/^[，\s、。；]+|[，\s、。；]+$/g, '')
                .trim();

            return cleaned;
        }

        // 核心 TTS 朗读方法（优先调用后端高品质神经网络音频，失败自动降级为本地 Web Speech API）
        async speak(text, triggerButton = null, onEnd = null) {
            // 如果正在朗读相同的按钮，则视为停止
            if (this.currentPlayingEl === triggerButton && (this.currentAudio || (this.synth && this.synth.speaking))) {
                this.stop();
                return;
            }

            // 停止之前的朗读
            this.stop();

            const cleanText = this.cleanTextForSpeech(text);
            if (!cleanText) return;

            this.currentPlayingEl = triggerButton;
            if (triggerButton) {
                triggerButton.classList.add('playing');
                triggerButton.setAttribute('title', '点击停止朗读');
            }

            console.log('[VoiceEngine] 🚀 触发发声朗读, 净化后文本:', cleanText.substring(0, 40));
            this._showToast('🔊 正在生成语音并准备朗读...');

            // 优先尝试后端高品质神经网络 TTS（兼容所有手机和浏览器）
            const voiceName = this.settings.persona === 'female' ? 'zh-CN-XiaoxiaoNeural' : 'zh-CN-YunxiNeural';
            let rateParam = '+0%';
            if (this.settings.rate === 1.2 || this.settings.rate === '1.2') rateParam = '+20%';
            if (this.settings.rate === 0.8 || this.settings.rate === '0.8') rateParam = '-20%';

            try {
                const apiBase = (window.API_BASE || 'http://localhost:8080/api/v1').replace(/\/+$/, '');
                const currentToken = localStorage.getItem('token');
                const reqHeaders = { 'Content-Type': 'application/json' };
                if (currentToken) reqHeaders['Authorization'] = `Bearer ${currentToken}`;

                console.log('[VoiceEngine] 📡 正在调用后端语音合成接口:', `${apiBase}/voice/tts`);
                const res = await fetch(`${apiBase}/voice/tts`, {
                    method: 'POST',
                    headers: reqHeaders,
                    body: JSON.stringify({
                        text: cleanText,
                        voice: voiceName,
                        rate: rateParam
                    })
                });

                console.log('[VoiceEngine] 📥 后端接口返回状态码:', res.status, res.statusText);

                const contentType = res.headers.get('Content-Type') || '';
                if (res.ok && (contentType.includes('audio') || contentType.includes('mpeg') || contentType.includes('octet-stream'))) {
                    const blob = await res.blob();
                    console.log('[VoiceEngine] 🎵 获取到 MP3 音频流，大小:', blob.size, 'bytes');

                    if (blob.size > 100) {
                        const audioUrl = URL.createObjectURL(blob);
                        const audio = new Audio(audioUrl);
                        audio.volume = 1.0;
                        this.currentAudio = audio;

                        this._showToast('🔊 正在语音朗读中...');

                        audio.onended = () => {
                            console.log('[VoiceEngine] ✅ 音频播放完毕');
                            this._cleanupPlaying(triggerButton);
                            URL.revokeObjectURL(audioUrl);
                            if (onEnd) onEnd();
                        };

                        audio.onerror = (err) => {
                            console.warn('[VoiceEngine] ⚠️ 音频播放遇到异常:', err);
                            URL.revokeObjectURL(audioUrl);
                            this._fallbackLocalSpeak(cleanText, triggerButton, onEnd);
                        };

                        await audio.play();
                        console.log('[VoiceEngine] 📢 真实音频正在耳机/扬声器中播放！');
                        return;
                    }
                } else {
                    console.warn('[VoiceEngine] ⚠️ 后端返回非音频格式:', res.status, contentType);
                    this._showToast(`⚠️ 语音服务响应异常 (${res.status})`, true);
                }
            } catch (netErr) {
                console.warn('[VoiceEngine] ❌ 请求后端 TTS 异常:', netErr);
                this._showToast('⚠️ 语音服务连接超时，尝试本地发声', true);
            }

            // 降级：本地 Web Speech API 朗读
            this._fallbackLocalSpeak(cleanText, triggerButton, onEnd);
        }

        // 浮层实时提示（手机屏幕顶部实时反馈）
        _showToast(message, isWarn = false) {
            let toast = document.getElementById('voiceToast');
            if (!toast) {
                toast = document.createElement('div');
                toast.id = 'voiceToast';
                toast.style.cssText = 'position:fixed;top:18px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:8px 18px;border-radius:24px;font-size:13px;z-index:99999;transition:all 0.3s;box-shadow:0 4px 12px rgba(0,0,0,0.15);pointer-events:none;display:flex;align-items:center;gap:6px;';
                document.body.appendChild(toast);
            }
            toast.textContent = message;
            toast.style.backgroundColor = isWarn ? 'rgba(250, 140, 22, 0.92)' : 'rgba(24, 144, 255, 0.92)';
            toast.style.opacity = '1';
            toast.style.display = 'block';

            if (this._toastTimer) clearTimeout(this._toastTimer);
            this._toastTimer = setTimeout(() => {
                toast.style.opacity = '0';
                setTimeout(() => { toast.style.display = 'none'; }, 300);
            }, 3000);
        }

        // 本地 Web Speech 兜底合成
        _fallbackLocalSpeak(cleanText, triggerButton, onEnd) {
            if (!this.synth) {
                this._cleanupPlaying(triggerButton);
                return;
            }

            try {
                const utterance = new SpeechSynthesisUtterance(cleanText);
                utterance.lang = 'zh-CN';
                utterance.rate = parseFloat(this.settings.rate) || 1.0;
                utterance.pitch = this.settings.persona === 'female' ? 1.2 : 0.9;

                const voices = this.synth.getVoices() || [];
                const zhVoices = voices.filter(v => v.lang && (v.lang.includes('zh') || v.lang.includes('cmn')));
                if (zhVoices.length > 0) {
                    if (this.settings.persona === 'female') {
                        utterance.voice = zhVoices.find(v => v.name.includes('Xiao') || v.name.includes('Female') || v.name.includes('女')) || zhVoices[0];
                    } else {
                        utterance.voice = zhVoices.find(v => v.name.includes('Yun') || v.name.includes('Male') || v.name.includes('男')) || zhVoices[0];
                    }
                }

                utterance.onend = () => {
                    this._cleanupPlaying(triggerButton);
                    if (onEnd) onEnd();
                };

                utterance.onerror = () => {
                    this._cleanupPlaying(triggerButton);
                };

                this.currentUtterance = utterance;
                this.synth.speak(utterance);
            } catch (e) {
                console.warn('本地语音合成异常:', e);
                this._cleanupPlaying(triggerButton);
            }
        }

        _cleanupPlaying(triggerButton) {
            if (this.currentPlayingEl) {
                this.currentPlayingEl.classList.remove('playing');
                this.currentPlayingEl.setAttribute('title', '朗读本题');
                this.currentPlayingEl = null;
            }
            if (triggerButton) {
                triggerButton.classList.remove('playing');
                triggerButton.setAttribute('title', '朗读本题');
            }
            this.currentAudio = null;
            this.currentUtterance = null;
        }

        // 停止当前所有语音播放
        stop() {
            if (this.currentAudio) {
                try {
                    this.currentAudio.pause();
                    this.currentAudio.currentTime = 0;
                } catch(e) {}
                this.currentAudio = null;
            }
            if (this.synth) {
                try { this.synth.cancel(); } catch(e) {}
            }
            this._cleanupPlaying();
        }

        // 切换自动播报开关 (面试页面顶部按钮)
        toggleAutoPlay() {
            this.settings.autoRead = !this.settings.autoRead;
            this.saveSettings({ autoRead: this.settings.autoRead });
            this.updateHeaderToggleBtn();
            if (!this.settings.autoRead) {
                this.stop();
            }
        }

        // 更新顶部按钮文案与高亮状态
        updateHeaderToggleBtn() {
            const btn = document.getElementById('voiceAutoBtn');
            if (!btn) return;
            if (this.settings.autoRead) {
                btn.className = 'btn-voice-toggle active';
                btn.innerHTML = '🔊 播报: 开';
                btn.setAttribute('title', '点击关闭自动朗读');
            } else {
                btn.className = 'btn-voice-toggle';
                btn.innerHTML = '🔇 播报: 关';
                btn.setAttribute('title', '点击开启自动朗读');
            }
        }

        // 切换语音录音输入 (STT) —— 点击直接录音，再点直接转文字
        async toggleVoiceInput(inputElId = 'answerInput', btnElId = 'micBtn') {
            const inputEl = document.getElementById(inputElId);
            const btnEl = document.getElementById(btnElId);

            // 如果当前正在录音，再次轻点则立即停止录音并触发转文字
            if (this.isRecording) {
                this.stopVoiceInput(btnEl, inputEl);
                return;
            }

            // 1. 在 HBuilderX 手机 App 环境 (使用 HTML5+ 原生录音机，0 配置极速启动)
            if (window.plus && plus.audio && typeof plus.audio.getRecorder === 'function') {
                try {
                    const recorder = plus.audio.getRecorder();
                    this.plusRecorder = recorder;
                    this.isRecording = true;
                    if (btnEl) {
                        btnEl.classList.add('recording');
                        btnEl.setAttribute('title', '正在倾听中... 再次点击结束并转文字');
                    }
                    if (inputEl) {
                        inputEl.focus();
                    }
                    this._showToast('🔴 正在倾听中... 请说话，说完再次轻点麦克风');

                    recorder.record({ filename: '_doc/audio/', format: 'wav', samplerate: 16000 }, async (filePath) => {
                        console.log('[STT] 1. 🎙️ 录音完成，原始本地路径:', filePath);
                        this._showToast('⏳ 正在将语音转为文字...');
                        const apiBase = (window.API_BASE || 'http://localhost:8080/api/v1').replace(/\/+$/, '');
                        const token = localStorage.getItem('token');

                        let uploadSuccess = false;

                        // 方案 A: 将 _doc 相对路径转换为系统全路径，使用 HTML5+ 原生 FileReader.readAsDataURL 转换为 Blob
                        try {
                            const fullPath = plus.io.convertLocalFileSystemURL(filePath);
                            console.log('[STT] 2. 转换为系统文件全路径:', fullPath);

                            await new Promise((resolve) => {
                                plus.io.resolveLocalFileSystemURL(fullPath, (entry) => {
                                    console.log('[STT] 3. 成功获取文件句柄:', entry.name);
                                    entry.file((file) => {
                                        console.log('[STT] 4. 文件元数据读取成功: 大小 =', file.size, '字节');
                                        const reader = new plus.io.FileReader();
                                        reader.onload = async (e) => {
                                            try {
                                                const dataUrl = e.target.result;
                                                console.log('[STT] 5. 📸 Base64 DataURL 读取成功, 字符长度:', (dataUrl || '').length);

                                                // 将 DataURL 转换为标准二进制 Blob
                                                const base64Content = dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl;
                                                const binaryStr = atob(base64Content);
                                                const len = binaryStr.length;
                                                const bytes = new Uint8Array(len);
                                                for (let i = 0; i < len; i++) {
                                                    bytes[i] = binaryStr.charCodeAt(i);
                                                }
                                                const audioBlob = new Blob([bytes], { type: 'audio/wav' });
                                                console.log('[STT] 6. 📦 二进制转换 Blob 成功, 大小:', audioBlob.size, '字节');

                                                const formData = new FormData();
                                                formData.append('file', audioBlob, 'record.wav');

                                                const reqHeaders = {};
                                                if (token) reqHeaders['Authorization'] = `Bearer ${token}`;

                                                console.log('[STT] 7. 📤 正在发送 HTTP POST 请求到:', `${apiBase}/voice/stt`);
                                                const res = await fetch(`${apiBase}/voice/stt`, {
                                                    method: 'POST',
                                                    headers: reqHeaders,
                                                    body: formData
                                                });

                                                console.log('[STT] 8. 📥 服务端响应状态:', res.status, res.statusText);
                                                if (res.ok) {
                                                    const result = await res.json();
                                                    console.log('[STT] 9. 📝 服务端返回完整 JSON:', JSON.stringify(result));
                                                    const text = result && result.data ? result.data.text : '';

                                                    const isRealText = text && !text.startsWith('（') && !text.includes('语音已接收') && !text.includes('未检测到') && !text.includes('请靠近麦克风');
                                                    if (isRealText) {
                                                        const targetInput = inputEl || document.getElementById('answerInput') || document.querySelector('textarea');
                                                        if (targetInput) {
                                                            targetInput.value = (targetInput.value ? targetInput.value + ' ' : '') + text;
                                                            targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                                                            if (typeof autoResize === 'function') autoResize(targetInput);
                                                        }
                                                        this._showToast('✅ 识别成功: ' + text);
                                                        console.log('[STT] 10. 🎉 真实识别文本填入成功:', targetInput ? targetInput.value : text);
                                                        uploadSuccess = true;
                                                        resolve();
                                                        return;
                                                    } else {
                                                        this._showToast(text || '💡 录音已处理，可在答题框修改补充。');
                                                    }
                                                }
                                            } catch (fetchErr) {
                                                console.warn('[STT] fetch 传输异常:', fetchErr);
                                            }
                                            resolve();
                                        };
                                        reader.onerror = (rErr) => {
                                            console.warn('[STT] FileReader 读取异常:', rErr);
                                            resolve();
                                        };
                                        reader.readAsDataURL(file);
                                    }, (fileErr) => {
                                        console.warn('[STT] entry.file 读取失败:', fileErr);
                                        resolve();
                                    });
                                }, (resolveErr) => {
                                    console.warn('[STT] resolveLocalFileSystemURL 路径解析失败:', resolveErr);
                                    resolve();
                                });
                            });
                        } catch (errA) {
                            console.warn('[STT] 方案 A 执行异常:', errA);
                        }

                        // 方案 B (备用通道): 若方案 A 未成功，使用原生 uploader 上传
                        if (!uploadSuccess) {
                            console.log('[STT] 🔄 自动切换为方案 B (plus.uploader 原生上传通道)...');
                            const task = plus.uploader.createUpload(`${apiBase}/voice/stt`, { method: 'POST' }, (t, status) => {
                                console.log('[STT] 📥 uploader 原生响应状态:', status, '内容:', t.responseText);
                                if (status === 200) {
                                    try {
                                        const res = JSON.parse(t.responseText);
                                        const text = res && res.data ? res.data.text : '';
                                        const isRealText = text && !text.startsWith('（') && !text.includes('语音已接收') && !text.includes('未检测到') && !text.includes('请靠近麦克风');
                                        if (isRealText) {
                                            const targetInput = inputEl || document.getElementById('answerInput') || document.querySelector('textarea');
                                            if (targetInput) {
                                                targetInput.value = (targetInput.value ? targetInput.value + ' ' : '') + text;
                                                targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                                                if (typeof autoResize === 'function') autoResize(targetInput);
                                            }
                                            this._showToast('✅ 识别成功: ' + text);
                                            console.log('[STT] 10. 🎉 原生通道真实文本填入成功:', targetInput ? targetInput.value : text);
                                            return;
                                        }
                                    } catch (e) {
                                        console.warn('[STT] uploader JSON 解析失败:', e);
                                    }
                                }
                                this._showToast('💡 录音已处理，可在答题框修改补充。');
                            });
                            task.addFile(filePath, { key: 'file' });
                            if (token) task.setRequestHeader('Authorization', `Bearer ${token}`);
                            task.start();
                        }
                    }, (err) => {
                        console.warn('[VoiceEngine] 原生录音异常:', err);
                        this.isRecording = false;
                        if (btnEl) btnEl.classList.remove('recording');
                        this._showToast('⚠️ 录音已取消');
                    });
                    return;
                } catch(e) {
                    console.warn('[VoiceEngine] 启动原生录音失败:', e);
                }
            }

            // 2. 在标准 Web / 浏览器 / 模拟器环境 (使用 HTML5 MediaRecorder 真实录音)
            if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    this.mediaStream = stream;
                    this.audioChunks = [];

                    let mimeType = 'audio/webm';
                    if (!MediaRecorder.isTypeSupported('audio/webm')) {
                        mimeType = MediaRecorder.isTypeSupported('audio/mp4') ? 'audio/mp4' : '';
                    }

                    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
                    this.mediaRecorder = recorder;

                    recorder.ondataavailable = (e) => {
                        if (e.data && e.data.size > 0) {
                            this.audioChunks.push(e.data);
                        }
                    };

                    recorder.onstop = async () => {
                        this._cleanupMediaStream();
                        if (this.audioChunks.length === 0) return;

                        const audioBlob = new Blob(this.audioChunks, { type: mimeType || 'audio/webm' });
                        console.log('[VoiceEngine] 🎙️ Web 录音完成，音频大小:', audioBlob.size, '字节，类型:', mimeType);
                        this._showToast('⏳ 正在将语音转为文字...');

                        try {
                            const apiBase = (window.API_BASE || 'http://localhost:8080/api/v1').replace(/\/+$/, '');
                            const formData = new FormData();
                            formData.append('file', audioBlob, 'voice_record.webm');

                            const currentToken = localStorage.getItem('token');
                            const reqHeaders = {};
                            if (currentToken) reqHeaders['Authorization'] = `Bearer ${currentToken}`;

                            console.log('[VoiceEngine] 📤 正在发送录音到后端接口:', `${apiBase}/voice/stt`);
                            const res = await fetch(`${apiBase}/voice/stt`, {
                                method: 'POST',
                                headers: reqHeaders,
                                body: formData
                            });

                            console.log('[VoiceEngine] 📥 STT 响应状态:', res.status, res.statusText);
                            if (res.ok) {
                                const result = await res.json();
                                console.log('[VoiceEngine] 📝 后端返回原始 JSON:', JSON.stringify(result));
                                const text = result && result.data ? result.data.text : '';
                                console.log('[VoiceEngine] 🎯 解析出的文字内容:', text);

                                if (text && !text.includes('未识别到') && !text.includes('已录制完成') && text !== '语音已接收') {
                                    if (inputEl) {
                                        inputEl.value = (inputEl.value ? inputEl.value + ' ' : '') + text;
                                        if (typeof autoResize === 'function') autoResize(inputEl);
                                    }
                                    this._showToast('✅ 识别成功: ' + text);
                                    console.log('[VoiceEngine] ✍️ 文本已填入答题框, 当前输入框值:', inputEl.value);
                                    return;
                                }
                            }
                        } catch (err) {
                            console.warn('[VoiceEngine] 录音上传异常:', err);
                        }

                        this._showToast('💡 录音已完成，可直接在答题框修改补充。');
                    };

                    recorder.start(250);
                    this.isRecording = true;
                    if (btnEl) {
                        btnEl.classList.add('recording');
                        btnEl.setAttribute('title', '正在倾听中... 再次点击结束并转文字');
                    }
                    this._showToast('🔴 正在录音中... 请说话，说完再次轻点麦克风');
                    return;

                } catch (micErr) {
                    console.warn('[VoiceEngine] 获取麦克风底层受限:', micErr);
                }
            }

            // 3. 兜底方案
            this._fallbackKeyboardInput(inputEl);
        }

        _cleanupMediaStream() {
            if (this.mediaStream) {
                this.mediaStream.getTracks().forEach(track => track.stop());
                this.mediaStream = null;
            }
        }

        stopVoiceInput(btnEl, inputEl) {
            this.isRecording = false;
            // 停止 HBuilderX 原生录音机
            if (this.plusRecorder && typeof this.plusRecorder.stop === 'function') {
                try { this.plusRecorder.stop(); } catch(e) {}
                this.plusRecorder = null;
            }
            // 停止 Web MediaRecorder 录音机
            if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
                try { this.mediaRecorder.stop(); } catch (e) {}
            }
            this._cleanupMediaStream();
            if (btnEl) {
                btnEl.classList.remove('recording');
                btnEl.setAttribute('title', '点击语音输入');
            }
        }

        // 手机端极速语音输入方案：激活输入框，引导使用手机输入法语音按键
        _fallbackKeyboardInput(inputEl) {
            if (inputEl) {
                inputEl.focus();
                const prevPlaceholder = inputEl.placeholder;
                inputEl.placeholder = '🎙️ 请点击手机键盘上的麦克风按钮说话，说完自动转文字...';
                this._showToast('🎙️ 请点下方手机键盘自带的麦克风按钮说话');
                setTimeout(() => {
                    inputEl.placeholder = prevPlaceholder || '输入你的回答，或点击麦克风语音作答...';
                }, 5000);
            }
        }
    }

    // 挂载全局单例
    window.voiceEngine = new VoiceEngine();

    // 快捷暴露给全局调用
    window.toggleAutoVoice = function() {
        if (window.voiceEngine) window.voiceEngine.toggleAutoPlay();
    };

    window.toggleVoiceInput = function() {
        if (window.voiceEngine) window.voiceEngine.toggleVoiceInput('answerInput', 'micBtn');
    };

    window.speakQuestion = function(text, btnEl) {
        if (window.voiceEngine) window.voiceEngine.speak(text, btnEl);
    };

    // 页面加载完成后同步按钮状态
    document.addEventListener('DOMContentLoaded', function() {
        if (window.voiceEngine) window.voiceEngine.updateHeaderToggleBtn();
    });
})();
