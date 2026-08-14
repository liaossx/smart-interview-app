// ============================================
// AI 语音交互引擎 (Voice Engine)
// 包含: TTS 语音朗读、STT 语音识别输入、快捷开关与全局偏好管理
// ============================================

(function() {
    class VoiceEngine {
        constructor() {
            this.synth = window.speechSynthesis || null;
            this.recognition = null;
            this.isRecording = false;
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
                persona: 'male',          // 'male' (儒雅男声) | 'female' (亲切女声)
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

        // 初始化浏览器原生语音识别
        initSpeechRecognition() {
            const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition || null;
            if (!SpeechRec) {
                console.info('当前环境不支持 Web SpeechRecognition，将提示用户手动输入');
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

        // 清理文本中的 Markdown 标记，让朗读更自然流畅
        cleanTextForSpeech(text) {
            if (!text) return '';
            return text
                .replace(/\*\*|__/g, '')           // 去除加粗
                .replace(/#+\s*/g, '')             // 去除标题
                .replace(/[`*~_]/g, '')            // 去除代码/特殊符号
                .replace(/\[(.*?)\]\(.*?\)/g, '$1')// 去除超链接
                .replace(/^[-\d.]+\s*/gm, '')      // 去除列表序号
                .replace(/[\r\n]+/g, '，')          // 换行替换为自然停顿逗号
                .trim();
        }

        // 核心 TTS 朗读方法
        speak(text, triggerButton = null, onEnd = null) {
            if (!this.synth) {
                console.warn('当前浏览器不支持 SpeechSynthesis');
                return;
            }

            // 如果正在朗读相同的按钮，则视为停止
            if (this.currentPlayingEl === triggerButton && this.synth.speaking) {
                this.stop();
                return;
            }

            // 停止之前的朗读
            this.stop();

            const cleanText = this.cleanTextForSpeech(text);
            if (!cleanText) return;

            try {
                const utterance = new SpeechSynthesisUtterance(cleanText);
                utterance.lang = 'zh-CN';
                utterance.rate = parseFloat(this.settings.rate) || 1.0;
                utterance.pitch = this.settings.persona === 'female' ? 1.2 : 0.9;

                // 挑选合适的中文声音
                const voices = this.synth.getVoices();
                const zhVoices = voices.filter(v => v.lang.includes('zh') || v.lang.includes('cmn'));
                if (zhVoices.length > 0) {
                    if (this.settings.persona === 'female') {
                        utterance.voice = zhVoices.find(v => v.name.includes('Xiao') || v.name.includes('Female') || v.name.includes('女')) || zhVoices[0];
                    } else {
                        utterance.voice = zhVoices.find(v => v.name.includes('Yun') || v.name.includes('Male') || v.name.includes('男')) || zhVoices[0];
                    }
                }

                this.currentPlayingEl = triggerButton;
                if (triggerButton) {
                    triggerButton.classList.add('playing');
                    triggerButton.setAttribute('title', '点击停止朗读');
                }

                utterance.onend = () => {
                    if (this.currentPlayingEl) {
                        this.currentPlayingEl.classList.remove('playing');
                        this.currentPlayingEl.setAttribute('title', '朗读本题');
                        this.currentPlayingEl = null;
                    }
                    if (onEnd) onEnd();
                };

                utterance.onerror = (e) => {
                    console.warn('TTS 播放中断或异常:', e);
                    if (this.currentPlayingEl) {
                        this.currentPlayingEl.classList.remove('playing');
                        this.currentPlayingEl = null;
                    }
                };

                this.currentUtterance = utterance;
                this.synth.speak(utterance);
            } catch (e) {
                console.error('发声失败:', e);
            }
        }

        // 停止当前所有语音播放
        stop() {
            if (this.synth) {
                this.synth.cancel();
            }
            if (this.currentPlayingEl) {
                this.currentPlayingEl.classList.remove('playing');
                this.currentPlayingEl.setAttribute('title', '朗读本题');
                this.currentPlayingEl = null;
            }
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

        // 切换语音录音输入 (STT)
        toggleVoiceInput(inputElId = 'answerInput', btnElId = 'micBtn') {
            const inputEl = document.getElementById(inputElId);
            const btnEl = document.getElementById(btnElId);

            if (!this.recognition) {
                alert('抱歉，当前浏览器/环境未开放语音识别接口，请直接使用键盘打字作答。');
                return;
            }

            if (this.isRecording) {
                this.stopVoiceInput(btnEl);
                return;
            }

            // 开始录音识别
            try {
                this.isRecording = true;
                if (btnEl) {
                    btnEl.classList.add('recording');
                    btnEl.setAttribute('title', '正在倾听中... 点击完成');
                }

                let finalTranscript = '';
                const originalValue = inputEl ? inputEl.value : '';

                this.recognition.onresult = (event) => {
                    let interimTranscript = '';
                    for (let i = event.resultIndex; i < event.results.length; ++i) {
                        if (event.results[i].isFinal) {
                            finalTranscript += event.results[i][0].transcript;
                        } else {
                            interimTranscript += event.results[i][0].transcript;
                        }
                    }
                    if (inputEl) {
                        inputEl.value = (originalValue ? originalValue + ' ' : '') + finalTranscript + interimTranscript;
                        if (typeof autoResize === 'function') autoResize(inputEl);
                    }
                };

                this.recognition.onerror = (event) => {
                    console.warn('语音识别错误:', event.error);
                    this.stopVoiceInput(btnEl);
                };

                this.recognition.onend = () => {
                    this.stopVoiceInput(btnEl);
                };

                this.recognition.start();
            } catch (e) {
                console.error('启动麦克风失败:', e);
                this.stopVoiceInput(btnEl);
            }
        }

        stopVoiceInput(btnEl) {
            this.isRecording = false;
            if (this.recognition) {
                try { this.recognition.stop(); } catch (e) {}
            }
            if (btnEl) {
                btnEl.classList.remove('recording');
                btnEl.setAttribute('title', '点击语音输入');
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
