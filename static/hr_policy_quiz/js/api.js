// Same origin as the JHS Timesnap platform — this module is mounted under /hr-quiz.
const API_BASE = "/hr-quiz";

function getToken(role) {
  return localStorage.getItem(role + "_token");
}

function setToken(role, token) {
  localStorage.setItem(role + "_token", token);
}

function clearToken(role) {
  localStorage.removeItem(role + "_token");
}

async function apiRequest(path, { method = "GET", body = null, role = null, isForm = false } = {}) {
  const headers = {};
  if (!isForm) headers["Content-Type"] = "application/json";
  if (role) {
    const token = getToken(role);
    if (token) headers["Authorization"] = "Bearer " + token;
  }

  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body ? (isForm ? body : JSON.stringify(body)) : null,
  });

  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }

  if (res.status === 401 && role) {
    // A stored token can go stale without the user doing anything wrong -
    // most commonly the server's JWT secret was rotated (e.g. a fresh local
    // .env), which invalidates every previously-issued token at once. Clear
    // it and reload once so the page's own bootstrap logic fetches a fresh
    // one, instead of the user having to know to clear localStorage by hand.
    // Guarded to one retry per tab session so a genuinely-unauthorized user
    // doesn't end up in a reload loop.
    const retryFlag = "auth_retry_" + role;
    if (!sessionStorage.getItem(retryFlag)) {
      clearToken(role);
      sessionStorage.setItem(retryFlag, "1");
      window.location.reload();
      return new Promise(() => {}); // page is reloading, never resolve
    }
  } else if (role) {
    sessionStorage.removeItem("auth_retry_" + role);
  }

  if (!res.ok) {
    const message = (data && data.detail) || "Something went wrong, please try again";
    const err = new Error(typeof message === "string" ? message : JSON.stringify(message));
    err.status = res.status;
    throw err;
  }
  return data;
}

function showError(el, message) {
  el.textContent = message;
  el.classList.add("show");
}

function hideError(el) {
  el.classList.remove("show");
  el.textContent = "";
}

function formatDateTime(isoString) {
  if (!isoString) return "-";
  const d = new Date(isoString);
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
