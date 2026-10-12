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

    if (!user) {
        try {
            const res = await fetch(`${ONEID_API_URL}/api/auth/me`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            if (res.ok) {
                user = await res.json();
                sessionStorage.setItem("nova_user", JSON.stringify(user));
                localStorage.setItem("nova_user", JSON.stringify(user));
            } else {
                sessionStorage.removeItem(ONEID_TOKEN_KEY);
                localStorage.removeItem(ONEID_TOKEN_KEY);
                sessionStorage.removeItem("nova_user");
                localStorage.removeItem("nova_user");
                return;
            }
        } catch {
            // 네트워크 오류 시 캐시가 없으면 유지
        }
    }

    const displayName = user ? (user.nickname || user.username) : "사용자";
    const pathname = window.location.pathname;
    const isUpload = pathname.endsWith("upload.html");
    const isPlayer = pathname.endsWith("player.html");

    let linksHtml = "";
    if (isUpload) {
        linksHtml = '<a href="index.html">홈</a>';
    } else if (isPlayer) {
        linksHtml = '<a href="index.html">홈</a><a href="upload.html">업로드</a>';
    } else {
        linksHtml = '<a href="upload.html">업로드</a>';
    }

    navButtons.innerHTML = `
        <span class="user-greeting" style="color: #4da6ff; font-weight: bold; display: inline-flex; align-items: center;">${displayName} 님</span>
        ${linksHtml}
        <a href="#" id="novaLogoutBtn" style="color: #ccc; cursor: pointer;">로그아웃</a>
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
