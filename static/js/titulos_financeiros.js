(() => {
    const root = document.querySelector("[data-titles-dashboard]");
    if (!root || typeof Chart === "undefined") return;
    const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
    const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
    const flow = JSON.parse(document.getElementById("titles-flow-data").textContent);
    const categories = JSON.parse(document.getElementById("titles-categories-data").textContent);
    const flowCanvas = root.querySelector("[data-titles-flow]");
    if (flowCanvas) new Chart(flowCanvas, {
        type: "bar",
        data: { labels: flow.labels, datasets: [{ label: root.dataset.titlesSeries, data: flow.valores, backgroundColor: "#4c8ff2", hoverBackgroundColor: "#2563eb", maxBarThickness: 32, borderRadius: 2 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${money.format(ctx.parsed.y)}` } } },
            scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 12, maxRotation: 45, font: { size: 10 } } }, y: { beginAtZero: true, grid: { color: "#edf1f6" }, ticks: { font: { size: 10 }, callback: value => `R$ ${compact.format(value)}` } } },
        },
    });
    const categoryCanvas = root.querySelector("[data-titles-categories]");
    if (categoryCanvas) new Chart(categoryCanvas, {
        type: "doughnut",
        data: { labels: categories.labels, datasets: [{ data: categories.valores, backgroundColor: categories.cores, borderWidth: 2, borderColor: "#fff" }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: "76%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.label}: ${money.format(ctx.parsed)}` } } } },
    });
})();
