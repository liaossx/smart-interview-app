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

            // 优先尝试后端高品质神经网络 TTS（兼容所有手机和浏览器）
            const voiceName = this.settings.persona === 'female' ? 'zh-CN-XiaoxiaoNeural' : 'zh-CN-YunxiNeural';
            let rateParam = '+0%';
            if (this.settings.rate === 1.2 || this.settings.rate === '1.2') rateParam = '+20%';
            if (this.settings.rate === 0.8 || this.settings.rate === '0.8') rateParam = '-20%';

            try {
                const apiBase = window.API_BASE || 'http://localhost:8080/api/v1';
                const res = await fetch(`${apiBase}/voice/tts`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: cleanText,
                        voice: voiceName,
                        rate: rateParam
                    })
                });

                const contentType = res.headers.get('Content-Type') || '';
                if (res.ok && (contentType.includes('audio') || contentType.includes('mpeg') || contentType.includes('octet-stream'))) {
                    const blob = await res.blob();
                    if (blob.size > 200) {
                        const audioUrl = URL.createObjectURL(blob);
                        const audio = new Audio(audioUrl);
                        this.currentAudio = audio;

                        audio.onended = () => {
                            this._cleanupPlaying(triggerButton);
                            URL.revokeObjectURL(audioUrl);
                            if (onEnd) onEnd();
                        };

                        audio.onerror = (err) => {
                            console.warn('后端音频播放失败，尝试降级本地合成:', err);
                            URL.revokeObjectURL(audioUrl);
                            this._fallbackLocalSpeak(cleanText, triggerButton, onEnd);
                        };

                        await audio.play();
                        return;
                    }
                }
            } catch (netErr) {
                console.warn('请求后端 TTS 接口异常，降级到本地合成:', netErr);
            }

            // 降级：本地 Web Speech API 朗读
            this._fallbackLocalSpeak(cleanText, triggerButton, onEnd);
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

        // 切换语音录音输入 (STT) —— 支持 HBuilderX App 和标准浏览器
        toggleVoiceInput(inputElId = 'answerInput', btnElId = 'micBtn') {
            const inputEl = document.getElementById(inputElId);
            const btnEl = document.getElementById(btnElId);

            if (this.isRecording) {
                this.stopVoiceInput(btnEl);
                return;
            }

            // 1. 优先检测 HBuilderX 原生 App 环境 (HTML5+ plus.speech)
            if (window.plus && plus.speech) {
                this.isRecording = true;
                if (btnEl) {
                    btnEl.classList.add('recording');
                    btnEl.setAttribute('title', '正在倾听中... 点击完成');
                }
                const originalValue = inputEl ? inputEl.value : '';

                plus.speech.startRecognize({
                    engine: 'baidu',
                    lang: 'zh-chs',
                    punctuation: true,
                    userInterface: false
                }, (resultText) => {
                    if (inputEl && resultText) {
                        inputEl.value = (originalValue ? originalValue + ' ' : '') + resultText;
                        if (typeof autoResize === 'function') autoResize(inputEl);
                    }
                    this.stopVoiceInput(btnEl);
                }, (err) => {
                    console.warn('手机原生语音识别异常:', err);
                    this.stopVoiceInput(btnEl);
                });
                return;
            }

            // 2. 检测浏览器标准 Web SpeechRecognition
            if (this.recognition) {
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
                    return;
                } catch (e) {
                    console.error('启动麦克风失败:', e);
                    this.stopVoiceInput(btnEl);
                }
            }

            // 3. 都不支持时的友好提示
            alert('提示：当前手机环境暂未开启录音权限或不支持网页语音识别，请直接使用输入法打字或语音输入。');
        }

        stopVoiceInput(btnEl) {
            this.isRecording = false;
            if (window.plus && plus.speech) {
                try { plus.speech.stopRecognize(); } catch(e) {}
            }
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
