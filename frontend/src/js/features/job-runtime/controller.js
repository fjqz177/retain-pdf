import { normalizeJobPayload, isTerminalStatus } from "../../job.js";
import { resetJobSecondaryState } from "../../state.js";
import { isReaderDialogOpen, setCancelButtonDisabled } from "../app-shell/view.js";
import {
  cachedEventsFor,
  cachedManifestFor,
  fetchAllJobEvents,
  cachedStageActionsFor,
  JOB_EVENTS_REFRESH_MS,
  JOB_MANIFEST_REFRESH_MS,
  JOB_POLL_INTERVAL_MS,
  JOB_STAGE_ACTIONS_REFRESH_MS,
  shouldRefreshSecondary,
  stopPolling,
} from "./runtime-state.js";
import { returnJobRuntimeToHome } from "./runtime-reset.js";

export function mountJobRuntimeFeature({
  state,
  apiPrefix,
  buildJobDetailEndpoint,
  fetchJobPayload,
  fetchJobEvents,
  fetchJobArtifactsManifest,
  fetchJobStageActions,
  retryJobStage,
  submitJson,
  renderJob,
  setText,
  setWorkflowSections,
  resetUploadProgress,
  resetUploadedFile,
  applyWorkflowMode,
  clearPageRanges,
  updateJobWarning,
  activateDetailTab,
  onReaderDialogSync,
  onReaderDialogClose,
}) {
  async function fetchJob(jobId) {
    const payload = await fetchJobPayload(jobId, apiPrefix);
    const cachedEvents = cachedEventsFor(state, jobId);
    const cachedManifest = cachedManifestFor(state, jobId);
    const cachedStageActions = cachedStageActionsFor(state, jobId);
    renderJob(payload, cachedEvents, cachedManifest, cachedStageActions);
    if (isReaderDialogOpen()) {
      onReaderDialogSync?.();
    }
    const job = normalizeJobPayload(payload);
    const terminal = isTerminalStatus(job.status);
    if (isTerminalStatus(job.status)) {
      stopPolling(state);
    }
    if (shouldRefreshSecondary(state.currentJobEventsFetchedAt, JOB_EVENTS_REFRESH_MS, terminal || !cachedEvents)) {
      void fetchAllJobEvents({ fetchJobEvents, apiPrefix, jobId })
        .then((eventsPayload) => {
          if (state.currentJobId !== jobId) {
            return;
          }
          state.currentJobEvents = eventsPayload;
          state.currentJobEventsJobId = jobId;
          state.currentJobEventsFetchedAt = Date.now();
          renderJob(payload, eventsPayload, cachedManifestFor(state, jobId), cachedStageActionsFor(state, jobId));
        })
        .catch(() => {
          // Event stream is secondary; keep main status usable even if events fail.
        });
    }
    if (shouldRefreshSecondary(state.currentJobManifestFetchedAt, JOB_MANIFEST_REFRESH_MS, terminal || !cachedManifest)) {
      void fetchJobArtifactsManifest(jobId, apiPrefix)
        .then((manifestPayload) => {
          if (state.currentJobId !== jobId) {
            return;
          }
          state.currentJobManifest = manifestPayload;
          state.currentJobManifestJobId = jobId;
          state.currentJobManifestFetchedAt = Date.now();
          renderJob(payload, cachedEventsFor(state, jobId), manifestPayload, cachedStageActionsFor(state, jobId));
        })
        .catch(() => {
          // Artifacts manifest is secondary; keep main status usable even if manifest fails.
        });
    }
    if (fetchJobStageActions && shouldRefreshSecondary(state.currentJobStageActionsFetchedAt, JOB_STAGE_ACTIONS_REFRESH_MS, terminal || !cachedStageActions)) {
      void fetchJobStageActions(jobId, apiPrefix)
        .then((stageActionsPayload) => {
          if (state.currentJobId !== jobId) {
            return;
          }
          state.currentJobStageActions = stageActionsPayload;
          state.currentJobStageActionsJobId = jobId;
          state.currentJobStageActionsFetchedAt = Date.now();
          renderJob(payload, cachedEventsFor(state, jobId), cachedManifestFor(state, jobId), stageActionsPayload);
        })
        .catch(() => {
          // Stage actions are secondary; keep main status usable even if action discovery fails.
        });
    }
  }

  function startPolling(jobId) {
    stopPolling(state);
    state.currentJobId = jobId;
    resetJobSecondaryState(state);
    if (!state.currentJobStartedAt) {
      state.currentJobStartedAt = new Date().toISOString();
    }
    const placeholderJob = {
      job_id: jobId,
      status: "queued",
      stage: "queued",
      current_stage: "queued",
      stage_detail: "正在读取任务状态...",
      created_at: state.currentJobStartedAt,
      started_at: state.currentJobStartedAt,
    };
    setWorkflowSections(placeholderJob);
    renderJob(placeholderJob);
    fetchJob(jobId).catch((err) => {
      setText("error-box", err.message);
    });
    state.timer = setInterval(() => {
      fetchJob(jobId).catch((err) => {
        setText("error-box", err.message);
      });
    }, JOB_POLL_INTERVAL_MS);
  }

  function returnToHome() {
    returnJobRuntimeToHome({
      state,
      onReaderDialogClose,
      setWorkflowSections,
      resetUploadProgress,
      resetUploadedFile,
      applyWorkflowMode,
      clearPageRanges,
      setText,
      updateJobWarning,
      activateDetailTab,
    });
  }

  async function cancelCurrentJob() {
    const jobId = state.currentJobId;
    if (!jobId) {
      setText("error-box", "当前没有可取消的任务");
      return;
    }
    setCancelButtonDisabled(true);
    try {
      await submitJson(`${buildJobDetailEndpoint(jobId, apiPrefix)}/cancel`, {});
      await fetchJob(jobId);
    } catch (err) {
      setText("error-box", err.message);
    }
  }

  async function retryStage(stage) {
    const jobId = state.currentJobId;
    const normalizedStage = `${stage || ""}`.trim();
    if (!jobId || !normalizedStage) {
      setText("error-box", "当前没有可重新执行的阶段");
      return;
    }
    try {
      setText("error-box", "-");
      const result = await retryJobStage(jobId, apiPrefix, normalizedStage);
      const nextJobId = `${result?.job_id || jobId}`.trim();
      if (nextJobId) {
        startPolling(nextJobId);
      } else {
        await fetchJob(jobId);
      }
    } catch (err) {
      setText("error-box", err.message || String(err));
    }
  }

  return {
    cancelCurrentJob,
    fetchJob,
    retryStage,
    returnToHome,
    startPolling,
    stopPolling,
  };
}
