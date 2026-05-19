import {
  DOWNLOAD_ANIMATION_PATH,
  OCR_ANIMATION_PATH,
  RENDER_ANIMATION_PATH,
  STAGE_ANIMATIONS,
  STAGE_FLOW,
  STAGE_LABELS,
  TRANSLATION_ANIMATION_PATH,
  UPLOAD_ANIMATION_PATH,
} from "./job-status-card-presets.js";
import {
  resolveVisualStageKeyForSnapshot,
} from "./job-status-card-visuals.js";
import { createStatusStageAnimationController } from "./job-status-card-animation.js";
import {
  setBackHomeVisible,
  setCancelEnabled,
  setElapsed,
  setProgress,
  syncPrimaryActions,
} from "./job-status-card-rendering.js";
import {
  resolveSelectedStage,
  syncStageFlow,
} from "./job-status-card-stage-flow.js";
import { syncTranslationSubstageStates } from "./job-status-card-substages.js";
import { jobStatusCardTemplate } from "./job-status-card-template.js";

class JobStatusCard extends HTMLElement {
  #stageAnimationController = null;
  #currentStageKey = "";
  #selectedStageKey = "";
  #manualStageSelection = false;
  #lastSnapshot = null;
  #currentJobId = "";
  #progressAnimationTimer = null;
  #displayedProgressByStage = {};

  connectedCallback() {
    if (this.dataset.hydrated === "1") {
      return;
    }
    this.dataset.hydrated = "1";
    this.id = this.id || "status-section";
    this.classList.add("card", "status-card", "hidden");
    this.#stageAnimationController = createStatusStageAnimationController(this);
    this.innerHTML = jobStatusCardTemplate({
      translationAnimationPath: TRANSLATION_ANIMATION_PATH,
      ocrAnimationPath: OCR_ANIMATION_PATH,
      uploadAnimationPath: UPLOAD_ANIMATION_PATH,
      downloadAnimationPath: DOWNLOAD_ANIMATION_PATH,
      renderAnimationPath: RENDER_ANIMATION_PATH,
    });
    this.querySelector("#status-stage-flow")?.addEventListener("click", (event) => {
      const button = event.target?.closest?.(".status-stage-step");
      const stageKey = button?.dataset?.stageKey || "";
      if (!stageKey || button.disabled) {
        return;
      }
      this.#manualStageSelection = true;
      this.#selectedStageKey = stageKey;
      this.#renderSelectedStage();
    });
    this.addEventListener("click", (event) => {
      const button = event.target?.closest?.(".status-stage-retry-btn");
      const stage = button?.dataset?.retryStage || "";
      if (!stage || button.disabled) {
        return;
      }
      this.dispatchEvent(new CustomEvent("retainpdf:retry-stage", {
        bubbles: true,
        composed: true,
        detail: { stage },
      }));
    });
  }

  disconnectedCallback() {
    this.#clearProgressAnimation();
  }

  setStagePresentation({ label = "等待中", value = "准备中", stageKey = "" } = {}) {
    const labelEl = this.querySelector("#status-ring-label");
    const valueEl = this.querySelector("#status-ring-value");
    const detailEl = this.querySelector("#status-stage-detail");
    const previousCurrentStageKey = this.#currentStageKey;
    this.#currentStageKey = `${stageKey || ""}`.trim();
    if (previousCurrentStageKey && previousCurrentStageKey !== this.#currentStageKey) {
      this.#manualStageSelection = false;
    }
    const selection = resolveSelectedStage({
      currentStageKey: this.#currentStageKey,
      selectedStageKey: this.#selectedStageKey,
      manualStageSelection: this.#manualStageSelection,
    });
    this.#selectedStageKey = selection.selectedStageKey;
    this.#manualStageSelection = selection.manualStageSelection;
    this.setStageFlow(this.#currentStageKey, this.#selectedStageKey);
    const selectedIsCurrent = !this.#selectedStageKey || this.#selectedStageKey === this.#currentStageKey;
    const visualStageKey = selectedIsCurrent ? resolveVisualStageKeyForSnapshot(this.#lastSnapshot, this.#currentStageKey) : this.#selectedStageKey;
    this.#stageAnimationController?.setStageVisualMode(visualStageKey);
    if (labelEl) {
      labelEl.textContent = selectedIsCurrent ? label : `${STAGE_LABELS[this.#selectedStageKey] || "阶段"} 阶段`;
    }
    if (valueEl) {
      valueEl.textContent = value;
    }
    if (detailEl) {
      detailEl.textContent = value;
    }
  }

  #effectiveFlowStageKey(snapshot = this.#lastSnapshot) {
    const stageKey = `${snapshot?.stageKey || ""}`.trim();
    if (STAGE_FLOW.includes(stageKey)) {
      return stageKey;
    }
    const progressByKey = snapshot?.stageProgressByKey || {};
    return [...STAGE_FLOW].reverse().find((key) => progressByKey[key]) || "";
  }

  setStageFlow(stageKey = "", selectedStageKey = "") {
    syncStageFlow(this, stageKey, selectedStageKey);
  }

  syncPrimaryActions({ pdfReady = false, readerReady = false } = {}) {
    syncPrimaryActions(this, { pdfReady, readerReady });
  }

  #syncTranslationSubstages(selectedStageKey, selectedIsCurrent, selectedProgress = null) {
    syncTranslationSubstageStates(
      this.querySelector(".status-substage-flow"),
      selectedStageKey,
      selectedIsCurrent,
      this.#lastSnapshot,
      selectedProgress,
    );
  }

  #normalizeSelectedProgress(progress = {}, fallback = {}) {
    const fallbackBySubstage = fallback?.bySubstage || {};
    const progressSubstageKey = progress?.substageKey || fallback?.substageKey || "";
    const substageFallback = progressSubstageKey ? fallbackBySubstage[progressSubstageKey] : null;
    const current = Number(progress?.current ?? progress?.progressCurrent ?? substageFallback?.current ?? substageFallback?.progressCurrent ?? fallback?.current ?? fallback?.progressCurrent);
    const total = Number(progress?.total ?? progress?.progressTotal ?? substageFallback?.total ?? substageFallback?.progressTotal ?? fallback?.total ?? fallback?.progressTotal);
    return {
      current: Number.isFinite(current) ? current : NaN,
      total: Number.isFinite(total) ? total : NaN,
      progressText: progress?.progressText || substageFallback?.progressText || fallback?.progressText || "",
      progressUnit: progress?.progressUnit || substageFallback?.progressUnit || fallback?.progressUnit || "",
      indeterminate: Boolean(progress?.indeterminate ?? progress?.progressIndeterminate ?? substageFallback?.indeterminate ?? substageFallback?.progressIndeterminate ?? fallback?.indeterminate ?? fallback?.progressIndeterminate),
      substageKey: progressSubstageKey,
      visualStageKey: progress?.visualStageKey || substageFallback?.visualStageKey || fallback?.visualStageKey || "",
    };
  }

  #clearProgressAnimation() {
    if (this.#progressAnimationTimer) {
      clearTimeout(this.#progressAnimationTimer);
      this.#progressAnimationTimer = null;
    }
  }

  setElapsed(value = "-") {
    setElapsed(this, value);
  }

  setProgress(options = {}) {
    setProgress(this, options);
  }

  setCancelEnabled(enabled) {
    setCancelEnabled(this, enabled);
  }

  setBackHomeVisible(visible) {
    setBackHomeVisible(this, visible);
  }

  renderSnapshot({
    jobId = "",
    status = "",
    label = "等待中",
    value = "准备中",
    stageKey = "",
    elapsed = "-",
    progressCurrent = NaN,
    progressTotal = NaN,
    progressFallbackText = "-",
    progressPercent = NaN,
    progressText = "",
    progressUnit = "",
    progressIndeterminate = false,
    substageKey = "",
    errorText = "",
    visualStageKey = "",
    stageProgressByKey = {},
    stageRetryActions = {},
    pdfReady = false,
    readerReady = false,
    cancelEnabled = false,
    backHomeVisible = false,
  } = {}) {
    const normalizedJobId = `${jobId || ""}`.trim();
    if (normalizedJobId && normalizedJobId !== this.#currentJobId) {
      this.#currentJobId = normalizedJobId;
      this.#clearProgressAnimation();
      this.#displayedProgressByStage = {};
      this.#manualStageSelection = false;
      this.#selectedStageKey = "";
    }
    this.#lastSnapshot = {
      jobId: normalizedJobId,
      status,
      label,
      value,
      stageKey,
      elapsed,
      progressCurrent,
      progressTotal,
      progressFallbackText,
      progressPercent,
      progressText,
      progressUnit,
      progressIndeterminate,
      substageKey,
      errorText,
      visualStageKey,
      stageProgressByKey,
      stageRetryActions,
      pdfReady,
      readerReady,
      cancelEnabled,
      backHomeVisible,
    };
    this.setStagePresentation({ label, value, stageKey });
    this.setElapsed(elapsed);
    this.#renderSelectedStage();
    this.setCancelEnabled(cancelEnabled);
    this.setBackHomeVisible(backHomeVisible);
  }

  #renderSelectedStage() {
    const snapshot = this.#lastSnapshot;
    if (!snapshot) {
      return;
    }
    const flowStageKey = this.#effectiveFlowStageKey(snapshot);
    const selected = this.#selectedStageKey || flowStageKey || snapshot.stageKey;
    const selectedIsCurrent = selected === snapshot.stageKey;
    this.setStageFlow(flowStageKey || snapshot.stageKey, selected);
    const selectedHistoricalProgress = selectedIsCurrent ? null : snapshot.stageProgressByKey?.[selected];
    this.#stageAnimationController?.setStageVisualMode(
      selectedHistoricalProgress?.visualStageKey || resolveVisualStageKeyForSnapshot(snapshot, selected),
    );
    const errorSummaryEl = this.querySelector("#status-stage-error-summary");
    const errorText = `${snapshot.errorText || ""}`.trim();
    const selectedIsError = snapshot.stageKey === "failed" || snapshot.stageKey === "canceled";
    const currentProgress = {
      current: snapshot.progressCurrent,
      total: snapshot.progressTotal,
      progressText: snapshot.progressText,
      progressUnit: snapshot.progressUnit,
      indeterminate: snapshot.progressIndeterminate,
      substageKey: snapshot.substageKey,
      visualStageKey: snapshot.visualStageKey,
    };
    const selectedProgress = selectedIsCurrent
      ? this.#normalizeSelectedProgress(currentProgress, snapshot.stageProgressByKey?.[selected])
      : this.#normalizeSelectedProgress(selectedHistoricalProgress);
    this.#syncTranslationSubstages(selected, selectedIsCurrent, selectedProgress);
    this.#stageAnimationController?.syncProgressSpeed({
      stageKey: selected,
      current: selectedProgress?.current,
      total: selectedProgress?.total,
    });
    if (errorSummaryEl) {
      errorSummaryEl.textContent = errorText;
      errorSummaryEl.classList.toggle("hidden", !selectedIsError || !errorText);
    }
    this.#setAnimatedProgress({
      selected,
      selectedIsCurrent,
      snapshot,
      selectedProgress,
    });
    this.syncPrimaryActions({
      pdfReady: selected === "done" && snapshot.pdfReady,
      readerReady: selected === "done" && snapshot.readerReady,
    });
    this.#renderStageRetryAction(selected, snapshot.stageRetryActions?.[selected]);
  }

  #setAnimatedProgress({ selected, selectedIsCurrent, snapshot, selectedProgress }) {
    const targetCurrent = Number(selectedProgress?.current);
    const targetTotal = Number(selectedProgress?.total);
    const status = `${snapshot?.status || ""}`.trim();
    const canAnimateRenderPages = selected === "render"
      && selectedIsCurrent
      && status === "running"
      && selectedProgress?.progressUnit !== "percent"
      && Number.isFinite(targetCurrent)
      && Number.isFinite(targetTotal)
      && targetTotal > 0
      && targetCurrent > 0;
    const previous = this.#displayedProgressByStage[selected];
    const rawPreviousCurrent = Number(previous?.current);
    const previousCurrent = Number.isFinite(rawPreviousCurrent) ? rawPreviousCurrent : 0;
    const previousTotal = Number(previous?.total);
    const shouldAnimate = canAnimateRenderPages
      && (!Number.isFinite(previousTotal) || previousTotal === targetTotal)
      && targetCurrent > previousCurrent + 1;
    if (!shouldAnimate) {
      this.#clearProgressAnimation();
      this.#displayedProgressByStage[selected] = {
        current: Number.isFinite(targetCurrent) ? targetCurrent : null,
        total: Number.isFinite(targetTotal) ? targetTotal : null,
      };
      this.setProgress({
        current: selectedProgress?.current,
        total: selectedProgress?.total,
        fallbackText: snapshot.progressFallbackText,
        percent: selectedIsCurrent ? snapshot.progressPercent : NaN,
        progressText: selectedProgress?.progressText || "",
        progressUnit: selectedProgress?.progressUnit || "",
        indeterminate: selectedProgress?.indeterminate,
        stageKey: selected,
        forceVisible: ["ocr", "translate", "render"].includes(selected)
          && (selectedIsCurrent || Boolean(selectedProgress)),
      });
      return;
    }

    this.#clearProgressAnimation();
    let displayedCurrent = previousCurrent;
    const tick = () => {
      displayedCurrent = Math.min(targetCurrent, displayedCurrent + 1);
      this.#displayedProgressByStage[selected] = {
        current: displayedCurrent,
        total: targetTotal,
      };
      const progressText = displayedCurrent >= targetCurrent
        ? selectedProgress?.progressText || ""
        : `第 ${displayedCurrent}/${targetTotal} 页`;
      this.setProgress({
        current: displayedCurrent,
        total: targetTotal,
        fallbackText: snapshot.progressFallbackText,
        percent: NaN,
        progressText,
        progressUnit: "",
        indeterminate: false,
        stageKey: selected,
        forceVisible: true,
      });
      if (displayedCurrent < targetCurrent) {
        this.#progressAnimationTimer = setTimeout(tick, 120);
      }
    };
    tick();
  }

  #renderStageRetryAction(selected, action) {
    const container = this.querySelector("#status-stage-retry");
    if (!container) {
      return;
    }
    if (!["ocr", "translate", "render"].includes(selected) || !action) {
      container.classList.add("hidden");
      container.replaceChildren();
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "status-stage-retry-btn";
    button.dataset.retryStage = action.stage || (selected === "translate" ? "translation" : selected);
    button.disabled = !action.canRetry;
    button.textContent = action.label || "重新执行";
    if (action.disabledReason) {
      button.title = action.disabledReason;
    }
    container.replaceChildren(button);
    container.classList.remove("hidden");
  }
}

if (!customElements.get("job-status-card")) {
  customElements.define("job-status-card", JobStatusCard);
}
