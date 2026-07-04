document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-bs-toggle='tooltip']").forEach((element) => {
        bootstrap.Tooltip.getOrCreateInstance(element);
    });
});
