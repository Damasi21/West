(() => {
    const root = document.querySelector("[data-titles-dashboard]");
    if (!root || typeof Chart === "undefined") return;
    const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
    const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
    const flow = JSON.parse(document.getElementById("titles-flow-data").textContent);
    const categories = JSON.parse(document.getElementById("titles-categories-data").textContent);
    const flowCanvas = root.querySelector("[data-titles-flow]");
    const flowChart = flowCanvas ? new Chart(flowCanvas, {
        type: "bar",
        data: { labels: flow.labels, datasets: [{ label: root.dataset.titlesSeries, data: flow.valores, backgroundColor: "#4c8ff2", hoverBackgroundColor: "#2563eb", maxBarThickness: 32, borderRadius: 2 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${money.format(ctx.parsed.y)}` } } },
            scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 12, maxRotation: 45, font: { size: 10 } } }, y: { beginAtZero: true, grid: { color: "#edf1f6" }, ticks: { font: { size: 10 }, callback: value => `R$ ${compact.format(value)}` } } },
        },
    }) : null;
    const toggle = root.querySelector("[data-titles-flow-toggle]");
    if (toggle && flowChart) {
        const paid = JSON.parse(document.getElementById("titles-paid-flow-data").textContent);
        let showPaid = false;
        toggle.addEventListener("click", () => {
            showPaid = !showPaid;
            const selected = showPaid ? paid : flow;
            toggle.textContent = showPaid ? "Contas a pagar" : "Contas pagas";
            toggle.setAttribute("aria-pressed", String(showPaid));
            toggle.title = showPaid ? "Mostrar saldos em aberto pela data do vencimento" : "Mostrar valores pagos pela data do pagamento";
            root.querySelector("[data-titles-flow-period]").textContent = `Por ${selected.granularidade} · ${showPaid ? "Pagamento" : "Vencimento"}`;
            root.querySelector("[data-titles-flow-region]").hidden = !selected.tem_dados;
            const empty = root.querySelector("[data-titles-flow-empty]");
            empty.hidden = selected.tem_dados;
            empty.querySelector("p").textContent = showPaid ? "Sem pagamentos com data e valor confirmados no periodo." : "Sem vencimentos em aberto no periodo.";
            flowCanvas.setAttribute("aria-label", showPaid ? "Valores pagos pela data do pagamento no periodo selecionado" : "Valores a pagar por vencimento no periodo selecionado");
            flowChart.stop();
            flowChart.data.labels = selected.labels;
            Object.assign(flowChart.data.datasets[0], { label: showPaid ? "Valor pago" : root.dataset.titlesSeries,
                data: selected.valores, backgroundColor: showPaid ? "#0f9488" : "#4c8ff2", hoverBackgroundColor: showPaid ? "#087c71" : "#2563eb" });
            flowChart.resize();
            flowChart.update("none");
        });
    }
    const categoryCanvas = root.querySelector("[data-titles-categories]");
    if (categoryCanvas) new Chart(categoryCanvas, {
        type: "doughnut",
        data: { labels: categories.labels, datasets: [{ data: categories.valores, backgroundColor: categories.cores, borderWidth: 2, borderColor: "#fff" }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: "76%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => `${ctx.label}: ${money.format(ctx.parsed)}` } } } },
    });
})();
