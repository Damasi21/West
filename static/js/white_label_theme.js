(() => {
    if (!document.body.hasAttribute("data-white-label-theme") || typeof Chart === "undefined") return;
    const primary = getComputedStyle(document.documentElement).getPropertyValue("--wl-link").trim();
    const blues = new Set(["#2563eb", "#4c8ff2", "#217ed4", "#3b82f6", "#09588c"]);
    const replace = value => Array.isArray(value) ? value.map(replace) : (typeof value === "string" && blues.has(value.toLowerCase()) ? primary : value);
    Chart.register({id: "whiteLabelPalette", beforeUpdate(chart) {
        for (const dataset of chart.data.datasets) for (const key of ["backgroundColor", "borderColor", "hoverBackgroundColor", "pointBackgroundColor"]) {
            if (dataset[key] !== undefined) dataset[key] = replace(dataset[key]);
        }
    }});
})();
