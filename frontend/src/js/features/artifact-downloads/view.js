export function isActionLinkDisabled(link) {
  return link.classList.contains("disabled") || link.getAttribute("aria-disabled") === "true";
}

export function bindProtectedArtifactLinks(handler) {
  document.querySelectorAll("#download-btn, #markdown-bundle-btn, #source-pdf-btn, #pdf-btn, #markdown-btn, #markdown-raw-btn")
    .forEach((node) => {
      node.addEventListener("click", handler);
    });
}
