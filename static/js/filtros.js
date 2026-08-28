window.OesteBI = window.OesteBI || {};

document.addEventListener("DOMContentLoaded", () => {
    const filters = document.querySelectorAll("[data-filter-dropdown]");

    const closeFilters = (except = null) => {
        filters.forEach((filter) => {
            if (filter !== except) {
                filter.classList.remove("is-open");
                filter.querySelector(".filter-trigger")?.setAttribute("aria-expanded", "false");
            }
        });
    };

    filters.forEach((filter) => {
        const trigger = filter.querySelector(".filter-trigger");
        const summary = filter.querySelector("[data-filter-summary]");

        trigger?.addEventListener("click", (event) => {
            event.stopPropagation();
            const willOpen = !filter.classList.contains("is-open");
            closeFilters(filter);
            filter.classList.toggle("is-open", willOpen);
            trigger.setAttribute("aria-expanded", String(willOpen));
        });

        filter.addEventListener("click", (event) => event.stopPropagation());

        const updateSummary = () => {
            if (!summary || !summary.dataset.emptyLabel) return;
            const checkboxes = filter.querySelectorAll("input[type='checkbox']");
            const checked = filter.querySelectorAll("input[type='checkbox']:checked").length;
            summary.textContent = checked === 0 || checked === checkboxes.length
                ? summary.dataset.emptyLabel
                : checked === 1
                    ? "1 selecionado"
                    : `${checked} selecionados`;
        };

        filter.querySelectorAll("input[type='checkbox']").forEach((input) => {
            input.addEventListener("change", updateSummary);
        });

        if (filter.matches("[data-category-filter]")) {
            const updateParents = () => {
                filter.querySelectorAll(".category-group").forEach((group) => {
                    const parent = group.querySelector("[data-category-parent]");
                    if (!parent) return;
                    const children = group.querySelectorAll("[data-category-child]");
                    const checked = group.querySelectorAll("[data-category-child]:checked").length;
                    parent.checked = children.length === 0 || checked === children.length;
                    parent.indeterminate = checked > 0 && checked < children.length;
                });
            };

            filter.querySelectorAll("[data-category-parent]").forEach((parent) => {
                parent.addEventListener("change", () => {
                    const group = parent.closest(".category-group");
                    group?.querySelectorAll("[data-category-child]").forEach((child) => {
                        child.checked = parent.checked;
                    });
                    parent.indeterminate = false;
                    updateSummary();
                });
            });

            filter.querySelectorAll("[data-category-child]").forEach((child) => {
                child.addEventListener("change", () => {
                    updateParents();
                    updateSummary();
                });
            });
            updateParents();
        }

        filter.querySelector("[data-select-all]")?.addEventListener("click", () => {
            filter.querySelectorAll("input[type='checkbox']").forEach((input) => {
                input.checked = true;
                input.indeterminate = false;
            });
            updateSummary();
        });

        filter.querySelector("[data-clear-all]")?.addEventListener("click", () => {
            filter.querySelectorAll("input[type='checkbox']").forEach((input) => {
                input.checked = false;
                input.indeterminate = false;
            });
            updateSummary();
        });

        const specificPeriod = filter.querySelector("[data-specific-period]");
        specificPeriod?.querySelectorAll("input[type='date']").forEach((input) => {
            input.addEventListener("focus", () => {
                const radio = filter.querySelector("input[value='personalizado']");
                if (radio) radio.checked = true;
            });
            input.addEventListener("change", () => {
                const radio = filter.querySelector("input[value='personalizado']");
                if (radio) radio.checked = true;
            });
        });
    });

    document.addEventListener("click", () => closeFilters());
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeFilters();
    });
});
