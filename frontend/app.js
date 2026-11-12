const tabs = document.querySelectorAll(".tabs button");
tabs.forEach(button => button.addEventListener("click", () => {
  tabs.forEach(tab => tab.classList.toggle("active", tab === button));
  document.querySelectorAll(".panel").forEach(panel => panel.classList.toggle("active", panel.id === button.dataset.tab));
}));

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "请求失败，请稍后重试");
  return body;
}

function show(id, message, isError = false) {
  const element = document.getElementById(id);
  element.textContent = message;
  element.classList.toggle("error", isError);
  element.hidden = false;
}

async function submit(form, action) {
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try { await action(); } finally { button.disabled = false; }
}

document.getElementById("checkin-photo").addEventListener("change", event => {
  const file = event.target.files[0];
  const preview = document.getElementById("checkin-preview");
  if (!file) { preview.hidden = true; return; }
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
});

document.getElementById("checkin-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  await submit(form, async () => {
    show("checkin-result", "照片已上传，正在云端检索…");
    try {
      const data = await api("/api/checkins", { method: "POST", body: new FormData(form) });
      const message = data.status === "success"
        ? `签到成功：${data.full_name}，${data.checked_at}`
        : data.status === "already_checked_in"
          ? `今天已签到：${data.full_name}，${data.checked_at}`
          : data.message;
      show("checkin-result", message, data.status === "unregistered");
    } catch (error) { show("checkin-result", error.message, true); }
  });
});

document.getElementById("register-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  await submit(form, async () => {
    show("register-result", "正在录入人脸，请稍候…");
    try {
      const data = await api("/api/register", { method: "POST", body: new FormData(form) });
      show("register-result", `${data.full_name}（${data.student_id}）注册成功，人脸已录入。`);
      form.reset();
    } catch (error) { show("register-result", error.message, true); }
  });
});

async function refreshAccount() {
  try {
    const user = await api("/api/me");
    document.getElementById("signed-out").hidden = true;
    document.getElementById("signed-in").hidden = false;
    document.getElementById("welcome").textContent = `你好，${user.full_name}`;
    const data = await api("/api/records");
    renderRows("records", data.records, item => [item.day, item.checked_at.slice(11, 19)]);
    const adminArea = document.getElementById("admin-area");
    adminArea.hidden = !user.is_admin;
    if (user.is_admin) {
      const users = await api("/api/admin/users");
      renderRows("admin-users", users.users, item => [item.full_name, item.student_id]);
      const allRecords = await api("/api/admin/records");
      renderRows("admin-records", allRecords.records, item => [item.full_name, item.checked_at]);
    }
  } catch {
    document.getElementById("signed-out").hidden = false;
    document.getElementById("signed-in").hidden = true;
  }
}

function renderRows(id, items, parts) {
    const list = document.getElementById(id);
    list.replaceChildren();
    if (!items.length) { list.textContent = "暂无记录"; return; }
    items.forEach(record => {
      const item = document.createElement("div");
      item.className = "record";
      const date = document.createElement("span");
      const [left, right] = parts(record);
      date.textContent = left;
      const time = document.createElement("strong");
      time.textContent = right;
      item.append(date, time);
      list.append(item);
    });
}

document.getElementById("login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  await submit(form, async () => {
    const values = Object.fromEntries(new FormData(form));
    try {
      await api("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      show("account-result", "登录成功");
      await refreshAccount();
    } catch (error) { show("account-result", error.message, true); }
  });
});

document.getElementById("logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  show("account-result", "已注销");
  await refreshAccount();
});

refreshAccount();
