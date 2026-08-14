// ============================================
// Mobile App Navigation & Native Features
// For HBuilderX / HTML5+ App
// ============================================

// --- Mobile Detection ---
function isMobile() {
    return window.innerWidth <= 768;
}

function isHBuilderApp() {
    return window.plus !== undefined;
}

// --- Drawer Menu ---
function toggleDrawer() {
    var sidebar = document.querySelector('.sidebar');
    var overlay = document.getElementById('drawerOverlay');
    var isOpen = sidebar.classList.contains('open');

    if (isOpen) {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
        setTimeout(function() { overlay.style.display = 'none'; }, 300);
    } else {
        overlay.style.display = 'block';
        // Force reflow for transition
        overlay.offsetHeight;
        overlay.classList.add('active');
        sidebar.classList.add('open');
    }
}

// --- Bottom Tab Navigation ---
function mobileNav(page) {
    showPage(page);
    updateTabHighlight(page);
    // Close drawer if open
    var sidebar = document.querySelector('.sidebar');
    if (sidebar && sidebar.classList.contains('open')) {
        toggleDrawer();
    }
    // Load profile page content
    if (page === 'profile') {
        loadProfile();
    }
}

function updateTabHighlight(page) {
    var tabs = document.querySelectorAll('.tab-btn');
    tabs.forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-page') === page);
    });
}

// Override showPage to also update tab highlight on mobile
var _originalShowPage = window.showPage;
window.showPage = function(name) {
    _originalShowPage(name);
    if (isMobile()) {
        // Map admin pages and other pages to no tab highlight
        var tabPages = ['dashboard', 'jd-input', 'history', 'profile'];
        if (tabPages.indexOf(name) !== -1) {
            updateTabHighlight(name);
        } else {
            // Clear all tab highlights for non-tab pages
            document.querySelectorAll('.tab-btn').forEach(function(btn) {
                btn.classList.remove('active');
            });
        }
    }
};

// --- Profile Page ---
function renderVoiceSettingsHtml() {
    var vs = window.voiceEngine ? window.voiceEngine.settings : { autoRead: false, persona: 'male', rate: 1.0 };
    return '<div class="card profile-section">' +
        '<h3>🎙️ 语音与交互设置</h3>' +
        '<div class="form-group" style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">' +
            '<label style="font-size:13px;margin:0;">新题自动朗读 (TTS)</label>' +
            '<input type="checkbox" id="voiceAutoReadToggle" ' + (vs.autoRead ? 'checked' : '') + ' onchange="updateVoiceSetting(\'autoRead\', this.checked)" style="width:20px;height:20px;cursor:pointer;">' +
        '</div>' +
        '<div class="form-group" style="margin-bottom:12px;">' +
            '<label style="font-size:13px;">面试官音色</label>' +
            '<select id="voicePersonaSelect" class="server-input" onchange="updateVoiceSetting(\'persona\', this.value)" style="padding:8px 12px;">' +
                '<option value="male" ' + (vs.persona === 'male' ? 'selected' : '') + '>儒雅男声（云希/男声）</option>' +
                '<option value="female" ' + (vs.persona === 'female' ? 'selected' : '') + '>亲切女声（晓晓/女声）</option>' +
            '</select>' +
        '</div>' +
        '<div class="form-group" style="margin-bottom:12px;">' +
            '<label style="font-size:13px;">朗读语速</label>' +
            '<select id="voiceRateSelect" class="server-input" onchange="updateVoiceSetting(\'rate\', parseFloat(this.value))" style="padding:8px 12px;">' +
                '<option value="0.8" ' + (vs.rate == 0.8 ? 'selected' : '') + '>0.8x 慢速</option>' +
                '<option value="1.0" ' + (vs.rate == 1.0 ? 'selected' : '') + '>1.0x 正常</option>' +
                '<option value="1.2" ' + (vs.rate == 1.2 ? 'selected' : '') + '>1.2x 快速</option>' +
            '</select>' +
        '</div>' +
    '</div>';
}

function updateVoiceSetting(key, val) {
    if (window.voiceEngine) {
        var update = {};
        update[key] = val;
        window.voiceEngine.saveSettings(update);
    }
}

function loadProfile() {
    var el = document.getElementById('profileContent');
    if (!el) return;

    if (!currentUser) {
        el.innerHTML = 
            '<div class="card profile-card">' +
                '<div class="profile-avatar">👤</div>' +
                '<p style="color:#999;margin-bottom:20px;">请先登录以使用完整功能</p>' +
                '<button class="btn-primary" onclick="showLogin()" style="width:100%;">登录 / 注册</button>' +
            '</div>' +
            renderVoiceSettingsHtml() +
            '<div class="card profile-section">' +
                '<h3>⚙️ 服务器设置</h3>' +
                '<div class="form-group" style="margin-bottom:12px;">' +
                    '<label style="font-size:13px;">API 服务器地址</label>' +
                    '<input type="text" id="serverUrl" class="server-input" value="' + window.API_BASE + '" placeholder="例如: http://192.168.1.100:8080/api/v1">' +
                '</div>' +
                '<button class="btn-secondary" style="width:100%;" onclick="saveServerUrl()">保存地址</button>' +
            '</div>';
        return;
    }

    el.innerHTML = 
        '<div class="card profile-card">' +
            '<div class="profile-avatar">👤</div>' +
            '<div class="profile-name">' + (currentUser.name || currentUser.username) + '</div>' +
            '<div class="profile-role">' + (currentUser.role === 'ADMIN' ? '🔧 管理员' : '普通用户') + '</div>' +
        '</div>' +
        renderVoiceSettingsHtml() +
        '<div class="card profile-section">' +
            '<h3>⚙️ 服务器设置</h3>' +
            '<div class="form-group" style="margin-bottom:12px;">' +
                '<label style="font-size:13px;">API 服务器地址</label>' +
                '<input type="text" id="serverUrl" class="server-input" value="' + window.API_BASE + '" placeholder="例如: http://192.168.1.100:8080/api/v1">' +
            '</div>' +
            '<button class="btn-secondary" style="width:100%;" onclick="saveServerUrl()">保存地址</button>' +
        '</div>' +
        '<div class="card profile-section">' +
            '<h3>📱 关于</h3>' +
            '<div style="font-size:13px;color:#999;">' +
                '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f0f0f0;"><span>版本</span><span>1.0.0</span></div>' +
                '<div style="display:flex;justify-content:space-between;padding:8px 0;"><span>运行环境</span><span>' + (isHBuilderApp() ? 'App' : '浏览器') + '</span></div>' +
            '</div>' +
        '</div>' +
        '<button class="btn-danger" style="margin-top:16px;" onclick="logout()">退出登录</button>';
}

// --- Server URL Management ---
function saveServerUrl() {
    var input = document.getElementById('serverUrl');
    if (!input) return;
    var url = input.value.trim();
    if (!url) {
        alert('请输入有效的服务器地址');
        return;
    }
    // Remove trailing slash
    url = url.replace(/\/+$/, '');
    window.API_BASE = url;
    localStorage.setItem('API_BASE', url);
    alert('服务器地址已保存!\n' + url);
}

// --- HTML5+ App Features ---
document.addEventListener('plusready', function() {
    // Android back button handling
    var backButtonPressedOnce = false;
    plus.key.addEventListener('backbutton', function() {
        // If drawer is open, close it
        var sidebar = document.querySelector('.sidebar');
        if (sidebar && sidebar.classList.contains('open')) {
            toggleDrawer();
            return;
        }
        // If on sub-page, go back to dashboard
        var currentPage = router.currentPage;
        if (currentPage && currentPage !== 'dashboard') {
            mobileNav('dashboard');
            return;
        }
        // Double-tap to exit
        if (backButtonPressedOnce) {
            plus.runtime.quit();
        } else {
            backButtonPressedOnce = true;
            plus.nativeUI.toast('再按一次退出应用');
            setTimeout(function() {
                backButtonPressedOnce = false;
            }, 2000);
        }
    });

    // Status bar
    try {
        plus.navigator.setStatusBarBackground('#1a73e8');
        plus.navigator.setStatusBarStyle('light');
    } catch(e) {}
});

// --- Register profile page with router ---
if (typeof router !== 'undefined') {
    router.register('profile', function() { loadProfile(); });
}
