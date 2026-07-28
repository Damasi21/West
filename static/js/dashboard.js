document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".metric-card").forEach((card, index) => {
        card.style.animationDelay = `${index * 60}ms`;
    });

    const chartBaseOptions = {
        responsive: true,
        maintainAspectRatio: false,
        animation: {
            duration: 900,
            easing: "easeOutQuart",
        },
        plugins: {
            legend: { display: false },
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: { color: "#667085", font: { size: 11 } },
            },
            y: {
                grid: { color: "rgba(148, 163, 184, .18)" },
                ticks: { color: "#667085", font: { size: 11 } },
            },
        },
    };
    const moneyFormatter = new Intl.NumberFormat("pt-BR", {
        style: "currency",
        currency: "BRL",
    });

    const resizeChartIn = (element) => {
        window.setTimeout(() => {
            if (typeof Chart === "undefined") return;
            element?.querySelectorAll("canvas").forEach((canvas) => {
                Chart.getChart(canvas)?.resize();
            });
        }, 80);
    };

    const setupSidebarToggle = () => {
        const sidebar = document.querySelector(".app-sidebar");
        const button = document.querySelector("[data-sidebar-toggle]");
        if (!sidebar || !button) return;

        const storageKey = "md21-sidebar-collapsed";
        const setCollapsed = (collapsed) => {
            sidebar.classList.toggle("is-collapsed", collapsed);
            button.setAttribute("aria-expanded", String(!collapsed));
            button.setAttribute("aria-label", collapsed ? "Expandir menu" : "Encolher menu");
            button.title = collapsed ? "Expandir menu" : "Encolher menu";
            const label = button.querySelector("span");
            if (label) label.textContent = collapsed ? "Expandir menu" : "Encolher menu";
            resizeChartIn(document);
        };

        setCollapsed(localStorage.getItem(storageKey) === "true");
        button.addEventListener("click", () => {
            const collapsed = !sidebar.classList.contains("is-collapsed");
            localStorage.setItem(storageKey, String(collapsed));
            setCollapsed(collapsed);
        });
    };

    const setupChartZoom = () => {
        if (!document.fullscreenEnabled) return;
        document.querySelectorAll(".dre-chart-card, .chart-card").forEach((card) => {
            if (!card.querySelector("canvas") || card.querySelector("[data-chart-zoom]")) return;
            card.querySelectorAll("canvas").forEach((canvas) => {
                canvas.parentElement?.classList.add("chart-zoom-canvas-region");
            });
            const header = card.querySelector(".dre-chart-header, .chart-header");
            if (!header) return;
            const button = document.createElement("button");
            button.type = "button";
            button.className = "chart-zoom-button";
            button.dataset.chartZoom = "true";
            button.title = "Abrir grafico em tela cheia";
            button.setAttribute("aria-label", "Abrir grafico em tela cheia");
            button.innerHTML = '<i class="bi bi-arrows-fullscreen"></i>';
            button.addEventListener("click", () => {
                if (document.fullscreenElement === card) {
                    document.exitFullscreen?.();
                    return;
                }
                card.classList.add("chart-card-fullscreen");
                card.requestFullscreen?.().then(() => resizeChartIn(card)).catch(() => {
                    card.classList.remove("chart-card-fullscreen");
                });
            });
            header.appendChild(button);
        });

        document.addEventListener("fullscreenchange", () => {
            const activeCard = document.fullscreenElement?.classList?.contains("chart-card-fullscreen")
                ? document.fullscreenElement
                : null;
            document.querySelectorAll(".chart-card-fullscreen").forEach((card) => {
                const buttonIcon = card.querySelector("[data-chart-zoom] i");
                if (card !== activeCard) {
                    card.classList.remove("chart-card-fullscreen");
                    if (buttonIcon) buttonIcon.className = "bi bi-arrows-fullscreen";
                } else if (buttonIcon) {
                    buttonIcon.className = "bi bi-fullscreen-exit";
                }
            });
            resizeChartIn(activeCard || document);
        });
    };

    setupSidebarToggle();
    setupChartZoom();

    const overview = document.querySelector("[data-finance-overview]");
    if (overview && typeof Chart !== "undefined") {
        const labels = JSON.parse(document.getElementById("overview-chart-labels").textContent);
        const receipts = JSON.parse(document.getElementById("overview-chart-receipts").textContent);
        const payments = JSON.parse(document.getElementById("overview-chart-payments").textContent);
        const margin = JSON.parse(document.getElementById("overview-chart-margin").textContent);
        const flowCanvas = overview.querySelector("[data-overview-flow-chart]");
        const marginCanvas = overview.querySelector("[data-overview-margin-chart]");

        if (flowCanvas) {
            new Chart(flowCanvas, {
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "Recebimentos",
                            data: receipts,
                            backgroundColor: "#0f766e",
                            borderRadius: 4,
                            maxBarThickness: 34,
                        },
                        {
                            label: "Pagamentos",
                            data: payments,
                            backgroundColor: "#f87171",
                            borderRadius: 4,
                            maxBarThickness: 34,
                        },
                    ],
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        legend: {
                            display: true,
                            align: "start",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.dataset.label}: ${moneyFormatter.format(context.parsed.y || 0)}`,
                            },
                        },
                    },
                },
            });
        }

        if (marginCanvas) {
            new Chart(marginCanvas, {
                type: "bar",
                data: {
                    labels,
                    datasets: [{
                        data: margin,
                        backgroundColor: margin.map((value) => value >= 0 ? "#0f766e" : "#dc2626"),
                        borderRadius: 4,
                        maxBarThickness: 34,
                    }],
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        ...chartBaseOptions.plugins,
                        tooltip: {
                            callbacks: {
                                label: (context) => `${(context.parsed.y || 0).toFixed(1).replace(".", ",")}%`,
                            },
                        },
                    },
                },
            });
        }
    }

    const cashflow = document.querySelector("[data-cashflow-dashboard]");
    if (cashflow && typeof Chart !== "undefined") {
        const labels = JSON.parse(document.getElementById("cashflow-chart-labels").textContent);
        const entradas = JSON.parse(document.getElementById("cashflow-chart-in").textContent);
        const saidas = JSON.parse(document.getElementById("cashflow-chart-out").textContent);
        const saldo = JSON.parse(document.getElementById("cashflow-chart-balance").textContent);
        const details = JSON.parse(document.getElementById("cashflow-chart-details").textContent);
        const pieIn = JSON.parse(document.getElementById("cashflow-pie-in").textContent);
        const pieOut = JSON.parse(document.getElementById("cashflow-pie-out").textContent);
        const palette = ["#0f766e", "#14b8a6", "#38bdf8", "#64748b", "#cbd5e1"];
        const confirmModal = cashflow.querySelector("[data-cashflow-confirm]");
        const confirmOk = cashflow.querySelector("[data-cashflow-confirm-ok]");
        const confirmCancel = cashflow.querySelector("[data-cashflow-confirm-cancel]");
        const detailModal = cashflow.querySelector("[data-cashflow-detail-modal]");
        const detailTitle = cashflow.querySelector("[data-cashflow-detail-title]");
        const detailKind = cashflow.querySelector("[data-cashflow-detail-kind]");
        const detailRows = cashflow.querySelector("[data-cashflow-detail-rows]");
        const detailClose = cashflow.querySelector("[data-cashflow-detail-close]");
        const detailSortDate = cashflow.querySelector("[data-cashflow-sort-date]");
        const detailSortValue = cashflow.querySelector("[data-cashflow-sort-value]");
        let pendingDetail = null;
        let currentDetailRows = [];
        let currentDetailSortField = "valor";
        let currentDetailSort = "desc";

        const closeCashflowConfirm = () => {
            if (confirmModal) confirmModal.hidden = true;
        };

        const closeCashflowDetails = () => {
            if (detailModal) detailModal.hidden = true;
        };

        const openCashflowDetails = (detail) => {
            if (!detailModal || !detailRows || !detailTitle || !detailKind) return;
            const month = details[detail.chave] || {};
            const rows = month[detail.tipo] || [];
            detailKind.textContent = detail.tipo === "entradas" ? "ENTRADAS" : "SAIDAS";
            detailTitle.textContent = `${detail.rotulo} - ${detail.label}`;
            currentDetailRows = [...rows];
            currentDetailSortField = "valor";
            currentDetailSort = "desc";
            renderCashflowDetailRows();
            detailModal.hidden = false;
        };

        const renderCashflowDetailRows = () => {
            if (!detailRows) return;
            detailRows.innerHTML = "";
            const updateSortButton = (button, field, descLabel, ascLabel) => {
                if (!button) return;
                const active = currentDetailSortField === field;
                const icon = button.querySelector("i");
                button.classList.toggle("is-active", active);
                button.setAttribute(
                    "aria-label",
                    active && currentDetailSort === "desc" ? ascLabel : descLabel,
                );
                if (icon) {
                    icon.className = active
                        ? (currentDetailSort === "desc" ? "bi bi-arrow-down-short" : "bi bi-arrow-up-short")
                        : "bi bi-arrow-down-up";
                }
            };
            updateSortButton(
                detailSortDate,
                "data",
                "Ordenar da data mais recente para a mais antiga",
                "Ordenar da data mais antiga para a mais recente",
            );
            updateSortButton(
                detailSortValue,
                "valor",
                "Ordenar do maior para o menor valor",
                "Ordenar do menor para o maior valor",
            );
            const rows = [...currentDetailRows].sort((a, b) => {
                if (currentDetailSortField === "data") {
                    const left = a.data?.split("/").reverse().join("-") || "";
                    const right = b.data?.split("/").reverse().join("-") || "";
                    return currentDetailSort === "desc"
                        ? right.localeCompare(left)
                        : left.localeCompare(right);
                }
                const left = Number(a.valor || 0);
                const right = Number(b.valor || 0);
                return currentDetailSort === "desc" ? right - left : left - right;
            });
            if (!rows.length) {
                const empty = document.createElement("div");
                empty.className = "cashflow-detail-empty";
                empty.textContent = "Sem contas para detalhar nesta coluna.";
                detailRows.appendChild(empty);
            } else {
                rows.forEach((item) => {
                    const row = document.createElement("div");
                    row.className = "cashflow-detail-row";
                    ["data", "nome", "categoria", "valor_fmt"].forEach((key) => {
                        const cell = document.createElement(key === "valor_fmt" ? "strong" : "span");
                        cell.textContent = item[key] || "";
                        row.appendChild(cell);
                    });
                    detailRows.appendChild(row);
                });
            }
        };

        const requestCashflowDetail = (detail) => {
            pendingDetail = detail;
            if (confirmModal) {
                confirmModal.hidden = false;
            }
        };

        confirmOk?.addEventListener("click", () => {
            closeCashflowConfirm();
            const detail = pendingDetail;
            pendingDetail = null;
            const openDetail = () => {
                if (detail) {
                    openCashflowDetails(detail);
                }
            };
            if (document.fullscreenElement) {
                document.exitFullscreen?.().then(openDetail).catch(openDetail);
                return;
            }
            openDetail();
        });
        confirmCancel?.addEventListener("click", () => {
            closeCashflowConfirm();
            pendingDetail = null;
        });
        detailClose?.addEventListener("click", closeCashflowDetails);
        detailSortDate?.addEventListener("click", () => {
            currentDetailSort = currentDetailSortField === "data" && currentDetailSort === "desc" ? "asc" : "desc";
            currentDetailSortField = "data";
            renderCashflowDetailRows();
        });
        detailSortValue?.addEventListener("click", () => {
            currentDetailSort = currentDetailSortField === "valor" && currentDetailSort === "desc" ? "asc" : "desc";
            currentDetailSortField = "valor";
            renderCashflowDetailRows();
        });
        confirmModal?.addEventListener("click", (event) => {
            if (event.target === confirmModal) {
                closeCashflowConfirm();
                pendingDetail = null;
            }
        });
        detailModal?.addEventListener("click", (event) => {
            if (event.target === detailModal) {
                closeCashflowDetails();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key !== "Escape") return;
            closeCashflowConfirm();
            closeCashflowDetails();
        });

        const mainCanvas = cashflow.querySelector("[data-cashflow-chart]");
        if (mainCanvas) {
            const mainCanvasRegion = cashflow.querySelector("[data-cashflow-chart-canvas]");
            if (mainCanvasRegion) {
                mainCanvasRegion.style.minWidth = `${Math.max(720, labels.length * 104)}px`;
            }
            const findCashflowHoverItem = (chart, event) => {
                const sourceEvent = event.native || event;
                if (sourceEvent.clientX == null || sourceEvent.clientY == null) return null;
                const rect = chart.canvas.getBoundingClientRect();
                const x = sourceEvent.clientX - rect.left;
                const y = sourceEvent.clientY - rect.top;

                for (const datasetIndex of [0, 1]) {
                    const meta = chart.getDatasetMeta(datasetIndex);
                    const item = meta.data.find((bar) => {
                        const props = bar.getProps(["x", "y", "base", "width"], true);
                        const left = props.x - props.width / 2;
                        const right = props.x + props.width / 2;
                        const top = Math.min(props.y, props.base);
                        const bottom = Math.max(props.y, props.base);
                        return x >= left && x <= right && y >= top && y <= bottom;
                    });
                    if (item) {
                        return { datasetIndex, index: meta.data.indexOf(item) };
                    }
                }

                const lineMeta = chart.getDatasetMeta(2);
                const point = lineMeta.data.find((element) => {
                    const props = element.getProps(["x", "y"], true);
                    return Math.hypot(x - props.x, y - props.y) <= 12;
                });
                return point ? { datasetIndex: 2, index: lineMeta.data.indexOf(point) } : null;
            };
            const formatCashflowShortValue = (value) => {
                const number = Number(value || 0);
                const sign = number < 0 ? "-" : "";
                const abs = Math.abs(number);
                const formatShortDecimal = (shortValue) => (
                    shortValue.toLocaleString("pt-BR", {
                        minimumFractionDigits: 0,
                        maximumFractionDigits: 1,
                    })
                );

                if (abs >= 1000000) {
                    return `${sign}${formatShortDecimal(abs / 1000000)}mi`;
                }
                if (abs >= 1000) {
                    const thousands = abs / 1000;
                    const display = thousands >= 100 ? Math.round(thousands).toLocaleString("pt-BR") : formatShortDecimal(thousands);
                    return `${sign}${display}mil`;
                }
                return `${sign}${Math.round(abs).toLocaleString("pt-BR")}`;
            };
            const cashflowBarLabelsPlugin = {
                id: "cashflowBarLabels",
                afterDatasetsDraw(chart) {
                    const { ctx, chartArea } = chart;
                    ctx.save();
                    ctx.font = "700 10px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
                    ctx.fillStyle = "#344054";
                    ctx.textAlign = "center";

                    [0, 1].forEach((datasetIndex) => {
                        const meta = chart.getDatasetMeta(datasetIndex);
                        const dataset = chart.data.datasets[datasetIndex];
                        meta.data.forEach((bar, index) => {
                            const value = Number(dataset.data[index] || 0);
                            const props = bar.getProps(["x", "y", "base"], true);
                            const isPositive = props.y <= props.base;
                            const y = isPositive
                                ? Math.max(chartArea.top + 10, props.y - 6)
                                : Math.min(chartArea.bottom - 10, props.y + 14);
                            ctx.textBaseline = isPositive ? "bottom" : "top";
                            ctx.fillText(formatCashflowShortValue(value), props.x, y);
                        });
                    });

                    ctx.restore();
                },
            };
            new Chart(mainCanvas, {
                plugins: [cashflowBarLabelsPlugin],
                data: {
                    labels,
                    datasets: [
                        {
                            type: "bar",
                            label: "Entradas",
                            data: entradas,
                            backgroundColor: "#0f766e",
                            borderRadius: 4,
                            barPercentage: .5,
                            categoryPercentage: .68,
                            maxBarThickness: 26,
                            yAxisID: "y",
                        },
                        {
                            type: "bar",
                            label: "Saidas",
                            data: saidas,
                            backgroundColor: "#f87171",
                            borderRadius: 4,
                            barPercentage: .5,
                            categoryPercentage: .68,
                            maxBarThickness: 26,
                            yAxisID: "y",
                        },
                        {
                            type: "line",
                            label: "Saldo acumulado",
                            data: saldo,
                            borderColor: "#1d4ed8",
                            backgroundColor: "#1d4ed8",
                            borderWidth: 2,
                            pointRadius: 3,
                            pointHoverRadius: 5,
                            pointHitRadius: 10,
                            tension: .35,
                            yAxisID: "y",
                        },
                    ],
                },
                options: {
                    ...chartBaseOptions,
                    layout: {
                        padding: { top: 20 },
                    },
                    interaction: {
                        mode: "point",
                        intersect: true,
                    },
                    plugins: {
                        legend: {
                            display: true,
                            align: "start",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.dataset.label}: ${moneyFormatter.format(context.parsed.y || 0)}`,
                            },
                        },
                    },
                    scales: chartBaseOptions.scales,
                    onHover: (event, elements, chart) => {
                        const item = findCashflowHoverItem(chart, event);
                        chart.canvas.style.cursor = item && item.datasetIndex <= 1 ? "pointer" : "default";
                        chart.setActiveElements(item ? [item] : []);
                        chart.tooltip?.setActiveElements(item ? [item] : [], {
                            x: event.x,
                            y: event.y,
                        });
                        chart.update("none");
                    },
                    onClick: (event, elements, chart) => {
                        const item = findCashflowHoverItem(chart, event);
                        if (!item || item.datasetIndex > 1) return;
                        const dataset = chart.data.datasets[item.datasetIndex];
                        const mes = labels[item.index];
                        const chave = Object.keys(details)[item.index];
                        requestCashflowDetail({
                            chave,
                            rotulo: mes,
                            label: dataset.label,
                            tipo: item.datasetIndex === 0 ? "entradas" : "saidas",
                        });
                    },
                },
            });
        }

        const renderPie = (canvas, data) => {
            if (!canvas) return;
            const labelsPie = data.map((item) => item.nome);
            const valuesPie = data.map((item) => item.valor);
            new Chart(canvas, {
                type: "doughnut",
                data: {
                    labels: labelsPie.length ? labelsPie : ["Sem dados"],
                    datasets: [{
                        data: valuesPie.length ? valuesPie : [1],
                        backgroundColor: labelsPie.length ? palette : ["#e5e7eb"],
                        borderWidth: 0,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "62%",
                    animation: {
                        duration: 900,
                        easing: "easeOutQuart",
                    },
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.label}: ${moneyFormatter.format(context.parsed || 0)}`,
                            },
                        },
                    },
                },
            });
        };

        renderPie(cashflow.querySelector("[data-cashflow-in-pie]"), pieIn);
        renderPie(cashflow.querySelector("[data-cashflow-out-pie]"), pieOut);
    }

    const delinquency = document.querySelector("[data-delinquency-dashboard]");
    if (delinquency && typeof Chart !== "undefined") {
        const agingLabels = JSON.parse(document.getElementById("aging-chart-labels").textContent);
        const agingValues = JSON.parse(document.getElementById("aging-chart-values").textContent);
        const trendLabels = JSON.parse(document.getElementById("delinquency-trend-labels").textContent);
        const trendValues = JSON.parse(document.getElementById("delinquency-trend-values").textContent);
        const agingCanvas = delinquency.querySelector("[data-aging-chart]");
        const trendCanvas = delinquency.querySelector("[data-delinquency-trend-chart]");

        if (agingCanvas) {
            new Chart(agingCanvas, {
                type: "bar",
                data: {
                    labels: agingLabels,
                    datasets: [{
                        data: agingValues,
                        backgroundColor: ["#f59e0b", "#f97316", "#ef4444", "#b91c1c", "#7f1d1d"],
                        borderRadius: 4,
                        maxBarThickness: 54,
                    }],
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        ...chartBaseOptions.plugins,
                        tooltip: {
                            callbacks: {
                                label: (context) => moneyFormatter.format(context.parsed.y || 0),
                            },
                        },
                    },
                },
            });
        }

        if (trendCanvas) {
            new Chart(trendCanvas, {
                type: "line",
                data: {
                    labels: trendLabels,
                    datasets: [{
                        data: trendValues,
                        borderColor: "#b91c1c",
                        backgroundColor: "#b91c1c",
                        borderWidth: 2,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        tension: .35,
                    }],
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        ...chartBaseOptions.plugins,
                        tooltip: {
                            callbacks: {
                                label: (context) => `${(context.parsed.y || 0).toFixed(1).replace(".", ",")}%`,
                            },
                        },
                    },
                },
            });
        }
    }

    const billing = document.querySelector("[data-billing-dashboard]");
    if (billing && typeof Chart !== "undefined") {
        const labels = JSON.parse(document.getElementById("billing-chart-labels").textContent);
        const products = JSON.parse(document.getElementById("billing-chart-products").textContent);
        const services = JSON.parse(document.getElementById("billing-chart-services").textContent);
        const previousAverage = JSON.parse(document.getElementById("billing-chart-previous-average").textContent);
        const accumulated = JSON.parse(document.getElementById("billing-chart-accumulated").textContent);
        const goal = JSON.parse(document.getElementById("billing-chart-goal").textContent);
        const totalByPeriod = products.map((value, index) => value + (services[index] || 0));
        const mainCanvas = billing.querySelector("[data-billing-main-chart]");
        const goalCanvas = billing.querySelector("[data-billing-goal-chart]");

        if (mainCanvas) {
            const mainCanvasRegion = billing.querySelector("[data-billing-main-chart-canvas]");
            if (mainCanvasRegion) {
                mainCanvasRegion.style.minWidth = `${Math.max(720, labels.length * 104)}px`;
            }
            const findBillingHoverItem = (chart, event) => {
                const sourceEvent = event.native || event;
                if (sourceEvent.clientX == null || sourceEvent.clientY == null) return null;
                const rect = chart.canvas.getBoundingClientRect();
                const x = sourceEvent.clientX - rect.left;
                const y = sourceEvent.clientY - rect.top;

                for (const datasetIndex of [0, 1]) {
                    const meta = chart.getDatasetMeta(datasetIndex);
                    const item = meta.data.find((bar) => {
                        const props = bar.getProps(["x", "y", "base", "width"], true);
                        const left = props.x - props.width / 2;
                        const right = props.x + props.width / 2;
                        const top = Math.min(props.y, props.base);
                        const bottom = Math.max(props.y, props.base);
                        return x >= left && x <= right && y >= top && y <= bottom;
                    });
                    if (item) {
                        return { datasetIndex, index: meta.data.indexOf(item) };
                    }
                }

                const billedMeta = chart.getDatasetMeta(3);
                const point = billedMeta.data.find((element) => {
                    const props = element.getProps(["x", "y"], true);
                    return Math.hypot(x - props.x, y - props.y) <= 12;
                });
                return point ? { datasetIndex: 3, index: billedMeta.data.indexOf(point) } : null;
            };
            const formatBillingShortValue = (value) => {
                const number = Number(value || 0);
                const sign = number < 0 ? "-" : "";
                const abs = Math.abs(number);
                const formatShortDecimal = (shortValue) => (
                    shortValue.toLocaleString("pt-BR", {
                        minimumFractionDigits: 0,
                        maximumFractionDigits: 1,
                    })
                );

                if (abs >= 1000000) {
                    return `${sign}${formatShortDecimal(abs / 1000000)}mi`;
                }
                if (abs >= 1000) {
                    const thousands = abs / 1000;
                    const display = thousands >= 100 ? Math.round(thousands).toLocaleString("pt-BR") : formatShortDecimal(thousands);
                    return `${sign}${display}mil`;
                }
                return `${sign}${Math.round(abs).toLocaleString("pt-BR")}`;
            };
            const billingBarLabelsPlugin = {
                id: "billingBarLabels",
                afterDatasetsDraw(chart) {
                    const { ctx, chartArea } = chart;
                    ctx.save();
                    ctx.font = "700 10px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
                    ctx.fillStyle = "#344054";
                    ctx.textAlign = "center";

                    [0, 1].forEach((datasetIndex) => {
                        const meta = chart.getDatasetMeta(datasetIndex);
                        const dataset = chart.data.datasets[datasetIndex];
                        meta.data.forEach((bar, index) => {
                            const value = Number(dataset.data[index] || 0);
                            const props = bar.getProps(["x", "y", "base"], true);
                            const isPositive = props.y <= props.base;
                            const y = isPositive
                                ? Math.max(chartArea.top + 10, props.y - 6)
                                : Math.min(chartArea.bottom - 10, props.y + 14);
                            ctx.textBaseline = isPositive ? "bottom" : "top";
                            ctx.fillText(formatBillingShortValue(value), props.x, y);
                        });
                    });

                    ctx.restore();
                },
            };
            new Chart(mainCanvas, {
                plugins: [billingBarLabelsPlugin],
                data: {
                    labels,
                    datasets: [
                        {
                            type: "bar",
                            label: "Produtos",
                            data: products,
                            backgroundColor: "#f59e0b",
                            borderRadius: 4,
                            barPercentage: .5,
                            categoryPercentage: .68,
                            maxBarThickness: 26,
                            yAxisID: "y",
                        },
                        {
                            type: "bar",
                            label: "Servicos",
                            data: services,
                            backgroundColor: "#93c5fd",
                            borderRadius: 4,
                            barPercentage: .5,
                            categoryPercentage: .68,
                            maxBarThickness: 26,
                            yAxisID: "y",
                        },
                        {
                            type: "line",
                            label: "Media anterior",
                            data: previousAverage,
                            borderColor: "#8a8f98",
                            backgroundColor: "#8a8f98",
                            borderDash: [6, 5],
                            borderWidth: 2,
                            pointRadius: 0,
                            tension: .35,
                            yAxisID: "y",
                        },
                        {
                            type: "line",
                            label: "Faturado",
                            data: accumulated,
                            borderColor: "#10b981",
                            backgroundColor: "#10b981",
                            borderWidth: 3,
                            pointRadius: 3,
                            pointHoverRadius: 5,
                            pointHitRadius: 10,
                            tension: .35,
                            yAxisID: "y",
                        },
                    ],
                },
                options: {
                    ...chartBaseOptions,
                    layout: {
                        padding: { top: 20 },
                    },
                    interaction: {
                        mode: "point",
                        intersect: true,
                    },
                    plugins: {
                        legend: {
                            display: true,
                            align: "start",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.dataset.label}: ${moneyFormatter.format(context.parsed.y || 0)}`,
                            },
                        },
                    },
                    scales: chartBaseOptions.scales,
                    onHover: (event, elements, chart) => {
                        const item = findBillingHoverItem(chart, event);
                        chart.canvas.style.cursor = item ? "default" : "default";
                        chart.setActiveElements(item ? [item] : []);
                        chart.tooltip?.setActiveElements(item ? [item] : [], {
                            x: event.x,
                            y: event.y,
                        });
                        chart.update("none");
                    },
                },
            });
        }

        if (goalCanvas) {
            new Chart(goalCanvas, {
                data: {
                    labels,
                    datasets: [
                        {
                            type: "bar",
                            label: "Faturamento",
                            data: totalByPeriod,
                            backgroundColor: "#93c5fd",
                            borderRadius: 4,
                            maxBarThickness: 34,
                        },
                        {
                            type: "line",
                            label: "Meta",
                            data: goal,
                            borderColor: "#dc2626",
                            backgroundColor: "#dc2626",
                            borderWidth: 2,
                            pointRadius: 0,
                            tension: .35,
                        },
                    ],
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        legend: {
                            display: true,
                            align: "start",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.dataset.label}: ${moneyFormatter.format(context.parsed.y || 0)}`,
                            },
                        },
                    },
                },
            });
        }
    }

    const sellerPerformance = document.querySelector("[data-seller-performance-dashboard]");
    if (sellerPerformance && typeof Chart !== "undefined") {
        const rankingLabels = JSON.parse(document.getElementById("seller-ranking-labels").textContent);
        const rankingRealized = JSON.parse(document.getElementById("seller-ranking-realized").textContent);
        const rankingMissing = JSON.parse(document.getElementById("seller-ranking-missing").textContent);
        const rankingGoal = JSON.parse(document.getElementById("seller-ranking-goal").textContent);
        const trendLabels = JSON.parse(document.getElementById("seller-trend-labels").textContent);
        const trendSeries = JSON.parse(document.getElementById("seller-trend-series").textContent);
        const rankingCanvas = sellerPerformance.querySelector("[data-seller-ranking-chart]");
        const trendCanvas = sellerPerformance.querySelector("[data-seller-trend-chart]");
        const palette = ["#2f7de1", "#10b981", "#f59e0b"];

        if (rankingCanvas) {
            new Chart(rankingCanvas, {
                type: "bar",
                data: {
                    labels: rankingLabels,
                    datasets: [
                        {
                            label: "Realizado",
                            data: rankingRealized,
                            backgroundColor: rankingRealized.map((value, index) => {
                                const percent = rankingGoal[index] ? (value / rankingGoal[index]) * 100 : 0;
                                if (percent >= 100) return "#b8dd91";
                                if (percent >= 80) return "#f7c56d";
                                return "#f4b8bd";
                            }),
                            borderColor: rankingRealized.map((value, index) => {
                                const percent = rankingGoal[index] ? (value / rankingGoal[index]) * 100 : 0;
                                if (percent >= 100) return "#7aa957";
                                if (percent >= 80) return "#e79d2d";
                                return "#d5717a";
                            }),
                            borderWidth: 1,
                            borderRadius: 4,
                        },
                        {
                            label: "Falta",
                            data: rankingMissing,
                            backgroundColor: "#edf0f6",
                            borderRadius: 4,
                        },
                    ],
                },
                options: {
                    ...chartBaseOptions,
                    indexAxis: "y",
                    plugins: {
                        legend: {
                            display: true,
                            align: "start",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.dataset.label}: ${moneyFormatter.format(context.parsed.x || 0)}`,
                            },
                        },
                    },
                    scales: {
                        x: {
                            stacked: true,
                            grid: { color: "rgba(148, 163, 184, .18)" },
                            ticks: {
                                color: "#667085",
                                font: { size: 11 },
                                callback: (value) => moneyFormatter.format(value),
                            },
                        },
                        y: {
                            stacked: true,
                            grid: { display: false },
                            ticks: { color: "#667085", font: { size: 11 } },
                        },
                    },
                },
            });
        }

        if (trendCanvas) {
            new Chart(trendCanvas, {
                type: "line",
                data: {
                    labels: trendLabels,
                    datasets: trendSeries.map((item, index) => ({
                        label: item.nome,
                        data: item.valores,
                        borderColor: palette[index % palette.length],
                        backgroundColor: palette[index % palette.length],
                        borderWidth: 3,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        tension: .35,
                    })),
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        legend: {
                            display: true,
                            align: "start",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.dataset.label}: ${moneyFormatter.format(context.parsed.y || 0)}`,
                            },
                        },
                    },
                },
            });
        }
    }

    const clientAnalysis = document.querySelector("[data-client-analysis-dashboard]");
    if (clientAnalysis && typeof Chart !== "undefined") {
        const segmentLabels = JSON.parse(document.getElementById("client-segment-labels").textContent);
        const segmentPercentages = JSON.parse(document.getElementById("client-segment-percentages").textContent);
        const segmentColors = JSON.parse(document.getElementById("client-segment-colors").textContent);
        const topLabels = JSON.parse(document.getElementById("client-top-labels").textContent);
        const topValues = JSON.parse(document.getElementById("client-top-values").textContent);
        const ticketLabels = JSON.parse(document.getElementById("client-ticket-labels").textContent);
        const ticketValues = JSON.parse(document.getElementById("client-ticket-values").textContent);
        const ticketFrequency = JSON.parse(document.getElementById("client-ticket-frequency").textContent);
        const segmentCanvas = clientAnalysis.querySelector("[data-client-segment-chart]");
        const topCanvas = clientAnalysis.querySelector("[data-client-top-chart]");
        const ticketCanvas = clientAnalysis.querySelector("[data-client-ticket-chart]");

        if (segmentCanvas) {
            new Chart(segmentCanvas, {
                type: "bar",
                data: {
                    labels: segmentLabels,
                    datasets: [
                        {
                            label: "% da carteira",
                            data: segmentPercentages,
                            backgroundColor: segmentColors,
                            borderRadius: 5,
                            maxBarThickness: 28,
                        },
                    ],
                },
                options: {
                    ...chartBaseOptions,
                    indexAxis: "y",
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.parsed.x || 0}% da carteira`,
                            },
                        },
                    },
                    scales: {
                        x: {
                            max: 100,
                            grid: { color: "rgba(148, 163, 184, .18)" },
                            ticks: {
                                color: "#667085",
                                font: { size: 11 },
                                callback: (value) => `${value}%`,
                            },
                        },
                        y: {
                            grid: { display: false },
                            ticks: { color: "#667085", font: { size: 11 } },
                        },
                    },
                },
            });
        }

        if (topCanvas) {
            new Chart(topCanvas, {
                type: "doughnut",
                data: {
                    labels: topLabels,
                    datasets: [
                        {
                            data: topValues,
                            backgroundColor: [
                                "#2f7de1",
                                "#16a34a",
                                "#f59e0b",
                                "#ef4444",
                                "#8b5cf6",
                                "#06b6d4",
                                "#84cc16",
                                "#f97316",
                                "#64748b",
                                "#db2777",
                                "#d7dde8",
                            ],
                            borderWidth: 2,
                            borderColor: "#ffffff",
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "58%",
                    plugins: {
                        legend: {
                            display: true,
                            position: "bottom",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 10 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => `${context.label}: ${moneyFormatter.format(context.parsed || 0)}`,
                            },
                        },
                    },
                },
            });
        }

        if (ticketCanvas) {
            new Chart(ticketCanvas, {
                data: {
                    labels: ticketLabels,
                    datasets: [
                        {
                            type: "bar",
                            label: "Ticket medio",
                            data: ticketValues,
                            backgroundColor: ["#b8c1f2", "#b8dd91", "#f7c56d", "#f4b8bd"],
                            borderColor: ["#7783db", "#7aa957", "#e79d2d", "#d5717a"],
                            borderWidth: 1,
                            borderRadius: 5,
                            yAxisID: "y",
                        },
                        {
                            type: "line",
                            label: "Freq. mensal",
                            data: ticketFrequency,
                            borderColor: "#10b981",
                            backgroundColor: "#10b981",
                            borderWidth: 3,
                            pointRadius: 4,
                            tension: .35,
                            yAxisID: "y1",
                        },
                    ],
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        legend: {
                            display: true,
                            align: "start",
                            labels: {
                                boxWidth: 9,
                                boxHeight: 9,
                                usePointStyle: true,
                                color: "#475467",
                                font: { size: 11 },
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    if (context.dataset.yAxisID === "y1") {
                                        return `${context.dataset.label}: ${context.parsed.y || 0}x/mes`;
                                    }
                                    return `${context.dataset.label}: ${moneyFormatter.format(context.parsed.y || 0)}`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: { color: "#667085", font: { size: 11 } },
                        },
                        y: {
                            grid: { color: "rgba(148, 163, 184, .18)" },
                            ticks: {
                                color: "#667085",
                                font: { size: 11 },
                                callback: (value) => moneyFormatter.format(value),
                            },
                        },
                        y1: {
                            position: "right",
                            grid: { display: false },
                            ticks: {
                                color: "#10b981",
                                font: { size: 11 },
                                callback: (value) => `${value}x/mes`,
                            },
                        },
                    },
                },
            });
        }
    }

    const marginDashboard = document.querySelector("[data-margin-dashboard]");
    if (marginDashboard && typeof Chart !== "undefined") {
        const bubbleData = JSON.parse(document.getElementById("margin-bubble-data").textContent);
        const bubbleCanvas = marginDashboard.querySelector("[data-margin-bubble-chart]");
        const datasetsByColor = bubbleData.reduce((acc, item) => {
            acc[item.cor] = acc[item.cor] || {
                label: item.faixa,
                data: [],
                backgroundColor: item.cor,
                borderColor: item.cor,
            };
            acc[item.cor].data.push(item);
            return acc;
        }, {});

        if (bubbleCanvas) {
            new Chart(bubbleCanvas, {
                type: "bubble",
                data: {
                    datasets: Object.values(datasetsByColor),
                },
                options: {
                    ...chartBaseOptions,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: (items) => items[0]?.raw?.produto || "",
                                label: (context) => {
                                    const item = context.raw;
                                    return [
                                        `Codigo: ${item.codigo}`,
                                        `Receita: ${moneyFormatter.format(item.x || 0)}`,
                                        `Margem: ${(item.y || 0).toFixed(1).replace(".", ",")}%`,
                                        `Volume: ${(item.volume || 0).toLocaleString("pt-BR")}`,
                                    ];
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            title: {
                                display: true,
                                text: "Receita",
                                color: "#667085",
                                font: { size: 11, weight: "600" },
                            },
                            grid: { color: "rgba(148, 163, 184, .18)" },
                            ticks: {
                                color: "#667085",
                                font: { size: 11 },
                                callback: (value) => moneyFormatter.format(value),
                            },
                        },
                        y: {
                            title: {
                                display: true,
                                text: "Margem bruta %",
                                color: "#667085",
                                font: { size: 11, weight: "600" },
                            },
                            grid: { color: "rgba(148, 163, 184, .18)" },
                            ticks: {
                                color: "#667085",
                                font: { size: 11 },
                                callback: (value) => `${value}%`,
                            },
                        },
                    },
                },
            });
        }
    }

    const dreDashboard = document.querySelector("[data-dre-dashboard]");
    if (!dreDashboard) return;

    const rows = [...dreDashboard.querySelectorAll("[data-row-id]")];
    const childrenByParent = rows.reduce((acc, row) => {
        const parentId = row.dataset.parentId;
        if (!parentId) return acc;
        acc[parentId] = acc[parentId] || [];
        acc[parentId].push(row);
        return acc;
    }, {});

    const setChildrenVisibility = (row, visible) => {
        const children = childrenByParent[row.dataset.rowId] || [];
        children.forEach((child) => {
            child.hidden = !visible;
            if (!visible) {
                const button = child.querySelector("[data-dre-row-toggle]");
                if (button) {
                    button.setAttribute("aria-expanded", "false");
                    button.querySelector("i").className = "bi bi-plus-lg";
                }
                setChildrenVisibility(child, false);
            }
        });
    };

    dreDashboard.querySelectorAll("[data-dre-row-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const row = button.closest("[data-row-id]");
            const expanded = button.getAttribute("aria-expanded") === "true";
            button.setAttribute("aria-expanded", String(!expanded));
            button.querySelector("i").className = expanded ? "bi bi-plus-lg" : "bi bi-dash-lg";
            setChildrenVisibility(row, !expanded);
        });
    });

    dreDashboard.querySelector("[data-dre-expand-all]")?.addEventListener("click", () => {
        dreDashboard.querySelectorAll("[data-dre-row-toggle]").forEach((button) => {
            button.setAttribute("aria-expanded", "true");
            button.querySelector("i").className = "bi bi-dash-lg";
        });
        rows.forEach((row) => {
            row.hidden = false;
        });
    });

    dreDashboard.querySelector("[data-dre-collapse-all]")?.addEventListener("click", () => {
        dreDashboard.querySelectorAll("[data-dre-row-toggle]").forEach((button) => {
            button.setAttribute("aria-expanded", "false");
            button.querySelector("i").className = "bi bi-plus-lg";
        });
        rows.forEach((row) => {
            row.hidden = Boolean(row.dataset.parentId);
        });
    });

    const fullscreenTarget = dreDashboard.querySelector("[data-dre-fullscreen]");
    dreDashboard.querySelector("[data-dre-fullscreen-button]")?.addEventListener("click", () => {
        if (!document.fullscreenElement) {
            fullscreenTarget?.requestFullscreen?.();
        } else {
            document.exitFullscreen?.();
        }
    });

    const labelsElement = document.getElementById("dre-chart-labels");
    const datasetsElement = document.getElementById("dre-chart-datasets");
    const select = dreDashboard.querySelector("[data-dre-chart-select]");
    const valuesCanvas = dreDashboard.querySelector("[data-dre-values-chart]");
    const ahCanvas = dreDashboard.querySelector("[data-dre-ah-chart]");
    if (!labelsElement || !datasetsElement || !select || !valuesCanvas || !ahCanvas || typeof Chart === "undefined") {
        return;
    }

    const labels = JSON.parse(labelsElement.textContent);
    const datasets = JSON.parse(datasetsElement.textContent);
    const valuesChart = new Chart(valuesCanvas, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                data: [],
                backgroundColor: "#0f766e",
                borderRadius: 4,
                maxBarThickness: 42,
            }],
        },
        options: {
            ...chartBaseOptions,
            plugins: {
                ...chartBaseOptions.plugins,
                tooltip: {
                    callbacks: {
                        label: (context) => moneyFormatter.format(context.parsed.y || 0),
                    },
                },
            },
        },
    });

    const ahChart = new Chart(ahCanvas, {
        type: "bar",
        data: {
            labels,
            datasets: [{
                data: [],
                backgroundColor: [],
                borderRadius: 4,
                maxBarThickness: 42,
            }],
        },
        options: {
            ...chartBaseOptions,
            plugins: {
                ...chartBaseOptions.plugins,
                tooltip: {
                    callbacks: {
                        label: (context) => `${(context.parsed.y || 0).toFixed(1).replace(".", ",")}%`,
                    },
                },
            },
        },
    });

    const updateCharts = () => {
        const current = datasets[select.value];
        if (!current) return;
        valuesChart.data.datasets[0].data = current.valores;
        ahChart.data.datasets[0].data = current.ah;
        ahChart.data.datasets[0].backgroundColor = current.ah.map((value) => (
            value >= 0 ? "#0f766e" : "#dc2626"
        ));
        valuesChart.update();
        ahChart.update();
    };

    select.addEventListener("change", updateCharts);
    updateCharts();
});
