import { buildFrontendPageUrl, isTrustedWindowMessage } from "../../config.js";
import {
  downloadBlob,
  fileNameFromDisposition,
  formatTransferSize,
  prepareDownloadTarget,
  saveResponseDownload,
} from "../../downloads.js";
import {
  completeDownloadToast,
  failDownloadToast,
  showDownloadPreparing,
  updateDownloadProgress,
} from "../../download-feedback.js";
import {
  resolveTranslatedPdfDownloadName,
  resolveManifestArtifactUrl,
} from "../../job-artifacts.js";
import { resolveJobActions } from "../../job.js";
import {
  bindReaderDialogEvents,
  closeReaderDialog,
  getReaderFrameWindow,
  getReaderLinkOpenState,
  getReaderToolbarButtonUrl,
  hasLoadedReaderFrame,
  openReaderDialog,
  restoreReaderButton,
  setReaderButtonBusy,
  setReaderFrameSource,
  setReaderLoadingProgress,
  setReaderLoadingVisible,
  setReaderToolbarButtonState,
} from "./view.js";

let pdfDocumentModulePromise = null;

async function loadPdfDocument() {
  if (!pdfDocumentModulePromise) {
    pdfDocumentModulePromise = import("../../../../vendor/pdf-lib/dist/pdf-lib.esm.js")
      .then((module) => module.PDFDocument);
  }
  return pdfDocumentModulePromise;
}

function jobIdFromReaderUrl(url) {
  const raw = `${url || ""}`.trim();
  if (!raw) {
    return "";
  }
  try {
    return new URL(raw, window.location.href).searchParams.get("job_id")?.trim() || "";
  } catch (_err) {
    return "";
  }
}

function currentReaderArtifactUrls(state) {
  const manifest = state.currentJobManifest;
  const job = state.currentJobSnapshot;
  const actions = job ? resolveJobActions(job) : null;
  const sourcePdf = resolveManifestArtifactUrl(manifest, "source_pdf");
  const translatedPdf = actions?.pdf || resolveManifestArtifactUrl(manifest, "pdf")
    || resolveManifestArtifactUrl(manifest, "translated_pdf")
    || resolveManifestArtifactUrl(manifest, "result_pdf");
  return { sourcePdf, translatedPdf };
}

function summarizeDownloadProgress(receivedBytes, totalBytes, percent) {
  const receivedText = formatTransferSize(receivedBytes);
  if (Number.isFinite(totalBytes) && totalBytes > 0) {
    const totalText = formatTransferSize(totalBytes);
    const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
    return `正在下载 ${receivedText} / ${totalText} (${safePercent.toFixed(0)}%)`;
  }
  return receivedText ? `正在下载 ${receivedText}` : "正在下载...";
}

async function downloadProtectedResource(
  fetchProtected,
  url,
  fallbackName,
  preferredName = "",
  onStatus = null,
  onBusy = null,
) {
  const suggestedName = `${preferredName || ""}`.trim() || fallbackName;
  const downloadTarget = await prepareDownloadTarget(suggestedName);
  if (downloadTarget.kind === "aborted") {
    return;
  }
  if (typeof onBusy === "function") {
    onBusy(true, "下载中...");
  }
  showDownloadPreparing(suggestedName);
  const resp = await fetchProtected(url);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`下载失败: ${resp.status} ${text || "unknown error"}`);
  }
  const disposition = resp.headers.get("content-disposition") || "";
  const finalName = `${preferredName || ""}`.trim() || fileNameFromDisposition(disposition, fallbackName);
  await saveResponseDownload(resp, {
    target: downloadTarget,
    filename: finalName,
    onProgress: ({ receivedBytes, totalBytes, percent, done }) => {
      if (typeof onStatus === "function") {
        onStatus({ filename: finalName, receivedBytes, totalBytes, percent, done });
      }
      if (typeof onBusy === "function") {
        onBusy(
          true,
          done
            ? "已完成"
            : Number.isFinite(percent)
              ? `${Math.max(0, Math.min(100, Number(percent) || 0)).toFixed(0)}%`
              : "下载中...",
        );
      }
      if (done) {
        completeDownloadToast(finalName);
        return;
      }
      updateDownloadProgress({ filename: finalName, receivedBytes, totalBytes, percent });
    },
  });
}

async function fetchProtectedBytes(fetchProtected, url, label) {
  const resp = await fetchProtected(url);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`读取${label}失败: ${resp.status} ${text || "unknown error"}`);
  }
  return resp.arrayBuffer();
}

async function buildMergedComparePdf(sourceBytes, translatedBytes) {
  const PDFDocument = await loadPdfDocument();
  const mergedDoc = await PDFDocument.create();
  const sourceDoc = await PDFDocument.load(sourceBytes);
  const translatedDoc = await PDFDocument.load(translatedBytes);
  const totalPages = Math.max(sourceDoc.getPageCount(), translatedDoc.getPageCount());

  for (let index = 0; index < totalPages; index += 1) {
    const sourceEmbedded = index < sourceDoc.getPageCount()
      ? (await mergedDoc.embedPdf(sourceBytes, [index]))[0]
      : null;
    const translatedEmbedded = index < translatedDoc.getPageCount()
      ? (await mergedDoc.embedPdf(translatedBytes, [index]))[0]
      : null;

    const sourceWidth = sourceEmbedded?.width || 0;
    const sourceHeight = sourceEmbedded?.height || 0;
    const translatedWidth = translatedEmbedded?.width || 0;
    const translatedHeight = translatedEmbedded?.height || 0;
    const pageWidth = Math.max(1, sourceWidth + translatedWidth);
    const pageHeight = Math.max(sourceHeight, translatedHeight, 1);
    const page = mergedDoc.addPage([pageWidth, pageHeight]);

    if (sourceEmbedded) {
      page.drawPage(sourceEmbedded, {
        x: 0,
        y: pageHeight - sourceHeight,
        width: sourceWidth,
        height: sourceHeight,
      });
    }
    if (translatedEmbedded) {
      page.drawPage(translatedEmbedded, {
        x: sourceWidth,
        y: pageHeight - translatedHeight,
        width: translatedWidth,
        height: translatedHeight,
      });
    }
  }

  return mergedDoc.save();
}

export function mountReaderDialogFeature({
  state,
  fetchProtected,
  setText,
}) {
  const progressState = {
    value: 0,
    target: 0,
    rafId: 0,
  };

  function buildReaderPageUrl(jobId) {
    const normalizedJobId = `${jobId || ""}`.trim();
    if (!normalizedJobId) {
      return "";
    }
    return buildFrontendPageUrl("./reader.html", {
      job_id: normalizedJobId,
    });
  }

  function buildReaderRouteUrl(jobId) {
    const normalizedJobId = `${jobId || ""}`.trim();
    const url = new URL(window.location.href);
    if (!normalizedJobId) {
      url.searchParams.delete("view");
      url.searchParams.delete("job_id");
      return url.toString();
    }
    url.searchParams.set("job_id", normalizedJobId);
    url.searchParams.set("view", "reader");
    return url.toString();
  }

  function syncReaderRoute(jobId = "") {
    window.history.replaceState(window.history.state, "", buildReaderRouteUrl(jobId));
  }

  function setLoading(loading) {
    setReaderLoadingVisible(loading);
  }

  function setLoadingProgress(percent = 0, text = "正在准备对照阅读…") {
    setReaderLoadingProgress(progressState, percent, text);
  }

  function syncToolbarActions() {
    const { sourcePdf, translatedPdf } = currentReaderArtifactUrls(state);
    setReaderToolbarButtonState("reader-source-download-btn", !!sourcePdf, sourcePdf);
    setReaderToolbarButtonState("reader-translated-download-btn", !!translatedPdf, translatedPdf);
    setReaderToolbarButtonState("reader-merged-download-btn", !!sourcePdf && !!translatedPdf);
  }

  async function handleSourceDownload() {
    const url = getReaderToolbarButtonUrl("reader-source-download-btn");
    if (!url) {
      return;
    }
    try {
      await downloadProtectedResource(
        fetchProtected,
        url,
        `${state.currentJobId || "result"}-source.pdf`,
        "",
        ({ filename, receivedBytes, totalBytes, percent, done }) => {
          setText("error-box", done ? `已开始保存 ${filename}` : summarizeDownloadProgress(receivedBytes, totalBytes, percent));
        },
        (busy, label) => setReaderButtonBusy("reader-source-download-btn", busy, label),
      );
    } catch (err) {
      setText("error-box", err.message);
      failDownloadToast(err.message || "下载失败");
    } finally {
      syncToolbarActions();
    }
  }

  async function handleTranslatedDownload() {
    const url = getReaderToolbarButtonUrl("reader-translated-download-btn");
    if (!url) {
      return;
    }
    try {
      const preferredName = resolveTranslatedPdfDownloadName(state, "");
      await downloadProtectedResource(
        fetchProtected,
        url,
        `${state.currentJobId || "result"}-translated.pdf`,
        preferredName,
        ({ filename, receivedBytes, totalBytes, percent, done }) => {
          setText("error-box", done ? `已开始保存 ${filename}` : summarizeDownloadProgress(receivedBytes, totalBytes, percent));
        },
        (busy, label) => setReaderButtonBusy("reader-translated-download-btn", busy, label),
      );
    } catch (err) {
      setText("error-box", err.message);
      failDownloadToast(err.message || "下载失败");
    } finally {
      syncToolbarActions();
    }
  }

  async function handleMergedDownload() {
    const { sourcePdf, translatedPdf } = currentReaderArtifactUrls(state);
    if (!sourcePdf || !translatedPdf) {
      return;
    }
    const previousMarkup = setReaderButtonBusy("reader-merged-download-btn", true, "生成中…");
    try {
      const [sourceBytes, translatedBytes] = await Promise.all([
        fetchProtectedBytes(fetchProtected, sourcePdf, "原始 PDF"),
        fetchProtectedBytes(fetchProtected, translatedPdf, "译文 PDF"),
      ]);
      const mergedBytes = await buildMergedComparePdf(sourceBytes, translatedBytes);
      const filename = `${state.currentJobId || "result"}-compare.pdf`;
      downloadBlob(new Blob([mergedBytes], { type: "application/pdf" }), filename);
      completeDownloadToast(filename);
    } catch (err) {
      setText("error-box", err.message);
      failDownloadToast(err.message || "下载失败");
    } finally {
      restoreReaderButton("reader-merged-download-btn", previousMarkup);
      syncToolbarActions();
    }
  }

  function resolveOpenArgs(input) {
    if (typeof input === "string") {
      return {
        url: buildReaderPageUrl(input),
        jobId: `${input || ""}`.trim(),
        disabled: false,
      };
    }
    if (input?.jobId || input?.url || typeof input?.disabled === "boolean") {
      const jobId = `${input?.jobId || ""}`.trim() || jobIdFromReaderUrl(input?.url);
      return {
        url: `${input?.url || buildReaderPageUrl(jobId)}`.trim(),
        jobId,
        disabled: !!input?.disabled,
      };
    }
    const { url, disabled } = getReaderLinkOpenState(input);
    let jobId = `${state.currentJobId || ""}`.trim();
    if (!jobId && url) {
      try {
        jobId = new URL(url, window.location.href).searchParams.get("job_id")?.trim() || "";
      } catch (_err) {
        jobId = "";
      }
    }
    return {
      url,
      jobId,
      disabled,
    };
  }

  function open(input) {
    const { url, jobId, disabled } = resolveOpenArgs(input);
    if (input?.preventDefault) {
      input.preventDefault();
    }
    if (disabled || !url || !jobId) {
      return;
    }
    syncReaderRoute(jobId);
    setLoading(true);
    setLoadingProgress(8, "正在准备对照阅读…");
    setReaderFrameSource(url);
    syncToolbarActions();
    openReaderDialog();
  }

  function close() {
    closeReaderDialog();
    setLoading(false);
    setLoadingProgress(0, "正在准备对照阅读…");
    setReaderToolbarButtonState("reader-source-download-btn", false);
    setReaderToolbarButtonState("reader-translated-download-btn", false);
    setReaderToolbarButtonState("reader-merged-download-btn", false);
    syncReaderRoute("");
    setReaderFrameSource("about:blank");
  }

  function bindEvents() {
    bindReaderDialogEvents({
      onClose: close,
      onSourceDownload: handleSourceDownload,
      onMergedDownload: handleMergedDownload,
      onTranslatedDownload: handleTranslatedDownload,
      onFrameLoad() {
        window.setTimeout(() => {
          if (hasLoadedReaderFrame()) {
            setLoading(false);
          }
        }, 1200);
      },
    });
    window.addEventListener("message", (event) => {
      if (!isTrustedWindowMessage(event, getReaderFrameWindow())) {
        return;
      }
      const data = event.data;
      if (!data || data.type !== "retainpdf-reader-progress") {
        return;
      }
      setLoading(true);
      setLoadingProgress(data.percent, data.text);
      if (Number(data.percent) >= 100 && data.stage === "ready") {
        window.setTimeout(() => {
          setLoading(false);
        }, 180);
      }
    });
  }

  return {
    bindEvents,
    close,
    getRequestedJobIdFromLocation() {
      const url = new URL(window.location.href);
      const view = `${url.searchParams.get("view") || ""}`.trim();
      const jobId = `${url.searchParams.get("job_id") || ""}`.trim();
      return view === "reader" && jobId ? jobId : "";
    },
    open,
    syncToolbarActions,
  };
}
