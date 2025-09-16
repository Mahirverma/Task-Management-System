const API_BASE = "http://127.0.0.1:8000";

function getToken() {
  return localStorage.getItem("access_token");
}

async function apiRequest(url, method = "GET", body = null) {
  const options = {
    method: method,
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${getToken()}`
    }
  };

  if (body) {
    options.body = JSON.stringify(body);
  }

  const resp = await fetch(`${API_BASE}${url}`, options);

  if (!resp.ok) {
    let msg;
    try {
      msg = await resp.json();
    } catch {
      msg = { detail: resp.statusText };
    }
    throw new Error(`API ${method} error ${resp.status}: ${JSON.stringify(msg)}`);
  }

  return resp.status !== 204 ? await resp.json() : null; // DELETE often returns 204
}

// Helpers for specific verbs
async function apiGet(url) { return apiRequest(url, "GET"); }
async function apiPost(url, body) { return apiRequest(url, "POST", body); }
async function apiPut(url, body) { return apiRequest(url, "PUT", body); }
async function apiPatch(url, body) { return apiRequest(url, "PATCH", body); }
async function apiDelete(url) { return apiRequest(url, "DELETE"); }

function logout() {
  localStorage.removeItem("access_token");
  window.location.href = "/login.html";
}