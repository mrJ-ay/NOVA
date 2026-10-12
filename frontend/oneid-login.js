import { API_BASE_URL } from "./api-config.js";
import { ONEID_API_URL, ONEID_CLIENT_ID, ONEID_TOKEN_KEY } from "./oneid-config.js";

const message = document.getElementById("message");
const button = document.getElementById("loginButton");
const migrationPanel = document.getElementById("migrationPanel");
const VERIFIER_KEY = "nova_oneid_verifier";
const STATE_KEY = "nova_oneid_state";
const RETURN_KEY = "nova_login_return_to";

function base64Url(bytes) {
    return btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function safeReturnTo(value) {
    return /^(index|upload|player)\.html(?:\?.*)?$/.test(value || "") ? value : "index.html";
}

async function beginLogin() {
    const verifier = base64Url(crypto.getRandomValues(new Uint8Array(32)));
    const state = base64Url(crypto.getRandomValues(new Uint8Array(24)));
    const challenge = base64Url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
    const redirectUri = new URL("login.html", location.href).href;
    const query = new URLSearchParams(location.search);
    sessionStorage.setItem(VERIFIER_KEY, verifier);
    sessionStorage.setItem(STATE_KEY, state);
    sessionStorage.setItem(RETURN_KEY, safeReturnTo(query.get("returnTo") || sessionStorage.getItem(RETURN_KEY)));
    const authorize = new URL("login.html", ONEID_API_URL);
    authorize.search = new URLSearchParams({ client_id: ONEID_CLIENT_ID, redirect_uri: redirectUri, code_challenge: challenge, state }).toString();
    location.assign(authorize.href);
}

async function finishSiteLogin(choice) {
    const token = sessionStorage.getItem(ONEID_TOKEN_KEY);
    const response = await fetch(`${API_BASE_URL}/api/auth/oneid/complete`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(choice),
    });
    const result = await response.json();
    if (response.status === 409 && result.detail === "ONEID_ACCOUNT_CHOICE_REQUIRED") {
        migrationPanel.hidden = false;
        message.textContent = "기존 계정을 연결하거나 새 NOVA 계정으로 시작하세요.";
        return;
    }
    if (!response.ok) throw new Error(result.detail || "NOVA 계정 연결에 실패했습니다.");
    const destination = safeReturnTo(sessionStorage.getItem(RETURN_KEY));
    sessionStorage.removeItem(RETURN_KEY);
    location.assign(destination);
}

async function completeLogin() {
    const params = new URLSearchParams(location.search);
    const code = params.get("code");
    if (!code) return;
    const state = params.get("state");
    const expectedState = sessionStorage.getItem(STATE_KEY);
    const verifier = sessionStorage.getItem(VERIFIER_KEY);
    history.replaceState(null, "", location.pathname);
    sessionStorage.removeItem(STATE_KEY);
    sessionStorage.removeItem(VERIFIER_KEY);
    if (!state || state !== expectedState || !verifier) throw new Error("로그인 연결을 확인하지 못했습니다. 다시 시도해 주세요.");
    const response = await fetch(`${ONEID_API_URL}/api/oauth/token`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: ONEID_CLIENT_ID, redirect_uri: new URL("login.html", location.href).href, code, code_verifier: verifier }),
    });
    const session = await response.json();
    if (!response.ok || !session.access_token) throw new Error(session.detail || "ONEID 로그인을 완료하지 못했습니다.");
    sessionStorage.setItem(ONEID_TOKEN_KEY, session.access_token);
    localStorage.setItem(ONEID_TOKEN_KEY, session.access_token);
    if (session.user) {
        sessionStorage.setItem("nova_user", JSON.stringify(session.user));
        localStorage.setItem("nova_user", JSON.stringify(session.user));
    }
    await finishSiteLogin({});
}

document.getElementById("linkLegacyButton").addEventListener("click", () => {
    const legacy_email = document.getElementById("legacyEmail").value.trim();
    const legacy_password = document.getElementById("legacyPassword").value;
    if (!legacy_email || !legacy_password) { message.textContent = "기존 이메일과 비밀번호를 입력하세요."; return; }
    finishSiteLogin({ legacy_email, legacy_password }).then(() => { document.getElementById("legacyPassword").value = ""; }).catch(error => { message.textContent = error.message; });
});
document.getElementById("createNewButton").addEventListener("click", () => finishSiteLogin({ create_new: true }).catch(error => { message.textContent = error.message; }));
button.addEventListener("click", () => beginLogin().catch(error => { message.textContent = error.message; }));
completeLogin().catch(error => { message.textContent = error.message; });