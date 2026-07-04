document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".metric-card").forEach((card, index) => {
        card.style.animationDelay = `${index * 60}ms`;
    });
});
