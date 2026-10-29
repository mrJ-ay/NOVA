import { ONEID_API_URL, ONEID_TOKEN_KEY } from "./oneid-config.js";

export async function initAuthNav() {
    const navButtons = document.querySelector(".nav-buttons");
    if (!navButtons) return;

    const token = sessionStorage.getItem(ONEID_TOKEN_KEY) || localStorage.getItem(ONEID_TOKEN_KEY);
    if (!token) return;

    let user = null;
    try {
        const cached = sessionStorage.getItem("nova_user") || localStorage.getItem("nova_user");
        if (cached) user = JSON.parse(cached);
    } catch {}

    function renderNav(u) {
        if (!u) return;
        const displayName = u.nickname || u.username || "사용자";
        const isAdmin = Boolean(u.is_admin || u.role === "admin");
        const pathname = window.location.pathname;
        const isUpload = pathname.endsWith("upload.html");
        const isPlayer = pathname.endsWith("player.html");
        const isAdminPage = pathname.endsWith("admin.html");

        let adminBtnHtml = "";
        if (isAdmin) {
            adminBtnHtml = `
                <a href="admin.html" style="background: #e50914; color: white; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; text-decoration: none; margin-right: 8px; display: inline-flex; align-items: center; cursor: pointer;">
                    관리자
                </a>
            `;
        }

        let linksHtml = "";
        if (isAdminPage) {
            linksHtml = '<a href="index.html">홈</a><a href="upload.html">업로드</a>';
        } else if (isUpload) {
            linksHtml = '<a href="index.html">홈</a>';
        } else if (isPlayer) {
            linksHtml = '<a href="index.html">홈</a><a href="upload.html">업로드</a>';
        } else {
            linksHtml = '<a href="upload.html">업로드</a>';
        }

        navButtons.innerHTML = `
            ${adminBtnHtml}
            <span class="user-greeting" style="color: #4da6ff; font-weight: bold; display: inline-flex; align-items: center; margin-right: 4px;">
                ${displayName} 님
            </span>
            ${linksHtml}
            <a href="https://oneid-helpdesk.onrender.com/?service=NOVA" target="_blank" rel="noopener">고객센터</a>
            <a href="#" id="novaLogoutBtn" style="color: #aaa; cursor: pointer;">로그아웃</a>
        `;

        const logoutBtn = document.getElementById("novaLogoutBtn");
        if (logoutBtn) {
            logoutBtn.addEventListener("click", (e) => {
                e.preventDefault();
                sessionStorage.removeItem(ONEID_TOKEN_KEY);
                localStorage.removeItem(ONEID_TOKEN_KEY);
                sessionStorage.removeItem("nova_user");
                localStorage.removeItem("nova_user");
                window.location.reload();
            });
        }
    }

    // 1. 캐시된 유저가 있으면 먼저 렌더링
    if (user) {
        renderNav(user);
    }

    // 2. ONEID 서버에서 최신 권한(role, is_admin 등)을 항상 조회하여 갱신
    try {
        const res = await fetch(`${ONEID_API_URL}/api/auth/me`, {
            headers: { Authorization: `Bearer ${token}` }
        });
        if (res.ok) {
            const freshUser = await res.json();
            sessionStorage.setItem("nova_user", JSON.stringify(freshUser));
            localStorage.setItem("nova_user", JSON.stringify(freshUser));
            renderNav(freshUser);
        } else if (res.status === 401) {
            // 토큰 만료
            sessionStorage.removeItem(ONEID_TOKEN_KEY);
            localStorage.removeItem(ONEID_TOKEN_KEY);
            sessionStorage.removeItem("nova_user");
            localStorage.removeItem("nova_user");
            window.location.reload();
        }
    } catch {
        // 네트워크 에러 시 기존 캐시 유지
    }
}
