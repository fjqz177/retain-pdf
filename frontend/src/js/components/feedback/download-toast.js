class DownloadToast extends HTMLElement {
  connectedCallback() {
    if (this.dataset.hydrated === "1") {
      return;
    }
    this.dataset.hydrated = "1";
    this.classList.add("download-toast", "hidden");
    this.setAttribute("aria-live", "polite");
    this.innerHTML = `
      <div class="download-toast-card">
        <div class="download-toast-head">
          <div id="download-toast-title" class="download-toast-title">下载中</div>
          <div id="download-toast-status" class="download-toast-status">正在准备...</div>
        </div>
        <div class="download-toast-track">
          <span id="download-toast-bar" class="download-toast-bar"></span>
        </div>
        <div id="download-toast-meta" class="download-toast-meta">等待响应...</div>
      </div>
    `;
  }

  setState({
    visible = false,
    title = "下载中",
    status = "正在准备...",
    meta = "等待响应...",
    percent = NaN,
    tone = "progress",
  } = {}) {
    this.classList.toggle("hidden", !visible);
    this.dataset.tone = tone;
    const titleEl = this.querySelector("#download-toast-title");
    const statusEl = this.querySelector("#download-toast-status");
    const metaEl = this.querySelector("#download-toast-meta");
    const barEl = this.querySelector("#download-toast-bar");
    if (titleEl) {
      titleEl.textContent = title;
    }
    if (statusEl) {
      statusEl.textContent = status;
    }
    if (metaEl) {
      metaEl.textContent = meta;
    }
    if (barEl) {
      const width = Number.isFinite(percent)
        ? Math.max(4, Math.min(100, Number(percent) || 0))
        : 18;
      barEl.style.width = `${width}%`;
    }
  }

  hide() {
    this.classList.add("hidden");
  }
}

if (!customElements.get("download-toast")) {
  customElements.define("download-toast", DownloadToast);
}
