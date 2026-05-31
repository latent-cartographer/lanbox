const form = document.querySelector("#shareForm");
const textInput = document.querySelector("#text");
const fileInput = document.querySelector("#files");
const dropzone = document.querySelector("#dropzone");
const selectedFiles = document.querySelector("#selectedFiles");
const statusEl = document.querySelector("#status");
const itemsEl = document.querySelector("#items");
const itemCount = document.querySelector("#itemCount");
const serverHint = document.querySelector("#serverHint");
const refreshBtn = document.querySelector("#refreshBtn");
const clearBtn = document.querySelector("#clearBtn");
const qrImage = document.querySelector("#qrImage");
const qrPanel = document.querySelector("#qrPanel");
const toggleQrBtn = document.querySelector("#toggleQrBtn");
const previewModal = document.querySelector("#previewModal");
const previewBackdrop = document.querySelector("#previewBackdrop");
const closePreviewBtn = document.querySelector("#closePreviewBtn");
const previewTitle = document.querySelector("#previewTitle");
const previewBody = document.querySelector("#previewBody");
const template = document.querySelector("#itemTemplate");

let currentFiles = [];
const deviceId = getOrCreateId(localStorage, "lanbox_device_id");
const tabId = getOrCreateId(sessionStorage, "lanbox_tab_id");
const clientId = `${deviceId}.${tabId}`;

function getOrCreateId(storage, key) {
  let value = storage.getItem(key);
  if (!value) {
    value = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    storage.setItem(key, value);
  }
  return value;
}

function setStatus(message, type = "") {
  statusEl.textContent = message;
  statusEl.className = `status ${type}`.trim();
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isUrl(text) {
  try {
    const url = new URL(text.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function renderText(text, target) {
  target.textContent = "";
  if (!text) return;
  if (isUrl(text)) {
    const link = document.createElement("a");
    link.href = text.trim();
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = text.trim();
    target.append(link);
    return;
  }
  target.textContent = text;
}

function previewKind(file) {
  const mime = file.mime || "";
  const name = (file.name || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  if (mime === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (mime.startsWith("text/") || /\.(txt|md|csv|json|log|xml|yml|yaml|ini|css|js|ts|html)$/i.test(name)) {
    return file.size <= 2 * 1024 * 1024 ? "text" : "";
  }
  return "";
}

function inlineUrl(file) {
  return `${file.url}${file.url.includes("?") ? "&" : "?"}inline=1`;
}

function buildCopyValue(item) {
  if (item.text) {
    return item.text;
  }
  if (item.title) {
    return item.title;
  }
  const files = item.files || [];
  return files.map((file) => file.name).join("\n").trim();
}

function copyLabelFor(item) {
  if (item.text) return "复制文本";
  if (item.title) return "复制标题";
  return "复制文件名";
}

function copiedMessageFor(item) {
  if (item.text) return "已复制文本";
  if (item.title) return "已复制标题";
  return "已复制文件名";
}

async function copyToClipboard(value) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Some mobile browsers still reject Clipboard API calls on LAN pages.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "-9999px";
  document.body.append(textarea);
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);
  const ok = document.execCommand("copy");
  textarea.remove();
  if (!ok) {
    throw new Error("复制失败");
  }
}

function closePreview() {
  previewModal.hidden = true;
  previewTitle.textContent = "文件预览";
  previewBody.textContent = "";
}

async function openPreview(file) {
  const kind = previewKind(file);
  if (!kind) return;
  previewTitle.textContent = file.name || "文件预览";
  previewBody.textContent = "";
  previewModal.hidden = false;

  if (kind === "image") {
    const image = document.createElement("img");
    image.className = "preview-media";
    image.src = inlineUrl(file);
    image.alt = file.name || "";
    previewBody.append(image);
    return;
  }
  if (kind === "video") {
    const video = document.createElement("video");
    video.className = "preview-media";
    video.src = inlineUrl(file);
    video.controls = true;
    previewBody.append(video);
    return;
  }
  if (kind === "audio") {
    const audio = document.createElement("audio");
    audio.src = inlineUrl(file);
    audio.controls = true;
    previewBody.append(audio);
    return;
  }
  if (kind === "pdf") {
    const frame = document.createElement("iframe");
    frame.className = "preview-frame";
    frame.src = inlineUrl(file);
    previewBody.append(frame);
    return;
  }
  if (kind === "text") {
    const pre = document.createElement("pre");
    pre.className = "preview-text";
    pre.textContent = "正在读取...";
    previewBody.append(pre);
    const response = await fetch(inlineUrl(file), { cache: "no-store" });
    pre.textContent = response.ok ? await response.text() : "预览失败";
  }
}

function renderSelectedFiles() {
  selectedFiles.textContent = "";
  currentFiles.forEach((file) => {
    const row = document.createElement("div");
    row.textContent = `${file.name} · ${formatBytes(file.size)}`;
    selectedFiles.append(row);
  });
}

function addFiles(fileList) {
  const next = Array.from(fileList || []);
  currentFiles = currentFiles.concat(next);
  renderSelectedFiles();
}

async function loadInfo() {
  try {
    const response = await fetch("/api/info", { cache: "no-store" });
    const info = await response.json();
    const address = info.addresses?.[0] || location.origin;
    serverHint.textContent = "内网设备临时传递板";
    qrImage.src = `/api/qr.svg?url=${encodeURIComponent(address)}`;
  } catch {
    serverHint.textContent = "局域网传递板";
    qrImage.src = `/api/qr.svg?url=${encodeURIComponent(location.origin)}`;
  }
}

async function loadItems() {
  const response = await fetch("/api/items", { cache: "no-store" });
  if (!response.ok) throw new Error("读取列表失败");
  const data = await response.json();
  renderItems(data.items || []);
}

function renderItems(items) {
  itemCount.textContent = String(items.length);
  itemsEl.textContent = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "还没有共享内容";
    itemsEl.append(empty);
    return;
  }

  items.forEach((item) => {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.id = item.id;
    node.querySelector(".meta").textContent = `${formatTime(item.created_at)} · ${item.client_ip || "unknown"} · ${item.saved ? "已保存" : "临时"}`;
    node.querySelector("h3").textContent = item.title || "";
    renderText(item.text || "", node.querySelector(".item-text"));

    const fileList = node.querySelector(".file-list");
    (item.files || []).forEach((file) => {
      const row = document.createElement("div");
      row.className = "file";
      const link = document.createElement("a");
      link.href = file.url;
      link.textContent = file.name;
      link.download = file.name;
      const controls = document.createElement("div");
      controls.className = "file-controls";
      const size = document.createElement("span");
      size.textContent = formatBytes(file.size);
      controls.append(size);
      if (previewKind(file)) {
        const previewButton = document.createElement("button");
        previewButton.type = "button";
        previewButton.className = "small-button";
        previewButton.textContent = "预览";
        previewButton.addEventListener("click", () => {
          openPreview(file).catch(() => setStatus("预览失败", "error"));
        });
        controls.append(previewButton);
      }
      row.append(link, controls);
      fileList.append(row);
    });

    const keepButton = node.querySelector(".keep");
    keepButton.disabled = Boolean(item.saved);
    keepButton.classList.toggle("saved", Boolean(item.saved));
    keepButton.title = item.saved ? "已保存" : "保存";
    keepButton.setAttribute("aria-label", item.saved ? "已保存" : "保存");
    keepButton.addEventListener("click", async () => {
      const response = await fetch(`/api/items/${encodeURIComponent(item.id)}/save`, { method: "POST" });
      if (!response.ok) {
        setStatus("保存失败", "error");
        return;
      }
      await loadItems();
      setStatus("已保存，不会随页面关闭自动删除", "ok");
    });

    const copyText = buildCopyValue(item);
    const copyButton = node.querySelector(".copy");
    const copyLabel = copyLabelFor(item);
    copyButton.disabled = !copyText;
    copyButton.title = copyLabel;
    copyButton.setAttribute("aria-label", copyLabel);
    copyButton.addEventListener("click", async () => {
      try {
        await copyToClipboard(copyText);
        setStatus(copiedMessageFor(item), "ok");
      } catch (error) {
        setStatus(error.message, "error");
      }
    });
    node.querySelector(".remove").addEventListener("click", async () => {
      const ok = window.confirm("删除这条共享内容？");
      if (!ok) return;
      const response = await fetch(`/api/items/${encodeURIComponent(item.id)}`, { method: "DELETE" });
      if (!response.ok) {
        setStatus("删除失败", "error");
        return;
      }
      await loadItems();
      setStatus("已删除", "ok");
    });

    itemsEl.append(node);
  });
}

fileInput.addEventListener("change", () => {
  addFiles(fileInput.files);
  fileInput.value = "";
});

dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropzone.classList.add("dragover");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("dragover");
});

dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragover");
  addFiles(event.dataTransfer.files);
});

document.addEventListener("paste", (event) => {
  const files = Array.from(event.clipboardData?.files || []);
  if (files.length) {
    addFiles(files);
    setStatus("已加入剪贴板文件", "ok");
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = form.querySelector("[type=submit]");
  submit.disabled = true;
  setStatus("正在发送...");
  try {
    const payload = new FormData();
    payload.append("text", textInput.value);
    currentFiles.forEach((file) => payload.append("files", file, file.name));
    const response = await fetch("/api/items", { method: "POST", body: payload });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "发送失败");
    form.reset();
    currentFiles = [];
    renderSelectedFiles();
    await loadItems();
    setStatus("已发送", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    submit.disabled = false;
  }
});

clearBtn.addEventListener("click", () => {
  form.reset();
  currentFiles = [];
  renderSelectedFiles();
  setStatus("");
});

toggleQrBtn.addEventListener("click", () => {
  const shouldShow = qrPanel.hidden;
  qrPanel.hidden = !shouldShow;
  toggleQrBtn.textContent = shouldShow ? "收起二维码" : "扫码进入";
});

closePreviewBtn.addEventListener("click", closePreview);
previewBackdrop.addEventListener("click", closePreview);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !previewModal.hidden) {
    closePreview();
  }
});

refreshBtn.addEventListener("click", async () => {
  setStatus("正在刷新...");
  try {
    await loadItems();
    setStatus("已刷新", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
});

async function heartbeat() {
  await fetch("/api/heartbeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId }),
    cache: "no-store",
  });
}

window.addEventListener("pagehide", () => {
  navigator.sendBeacon(`/api/clients/${encodeURIComponent(clientId)}/close`);
});

heartbeat().catch(() => {});
setInterval(() => {
  heartbeat().catch(() => {});
}, 5000);
loadInfo();
loadItems().catch((error) => setStatus(error.message, "error"));
setInterval(() => {
  loadItems().catch(() => {});
}, 5000);
