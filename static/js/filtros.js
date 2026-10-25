window.OesteBI = window.OesteBI || {};

document.addEventListener("DOMContentLoaded", () => {
    const filters = document.querySelectorAll("[data-filter-dropdown]");
    document.querySelectorAll("[data-dashboard-filters]").forEach(form => {
        const toggle = form.querySelector("[data-module-share-toggle]");
        const value = form.querySelector("[data-module-share-value]");
        toggle?.addEventListener("click", () => {
            const active = value.value !== "1";
            value.value = active ? "1" : "0";
            toggle.classList.toggle("is-active", active);
            toggle.setAttribute("aria-pressed", String(active));
            toggle.title = active ? "Compartilhamento ativado. Clique em Atualizar para aplicar ao modulo." : "Compartilhamento desligado. Clique em Atualizar para aplicar apenas neste dashboard.";
        });
    });

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
            if (willOpen) filter.querySelector("[data-category-search]")?.focus();
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
            const search = filter.querySelector("[data-category-search]");
            const clearSearch = filter.querySelector("[data-category-search-clear]");
            const searchStatus = filter.querySelector("[data-category-search-status]");
            const normalize = value => (value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
            const groups = [...filter.querySelectorAll(".category-group")].map(group => ({
                element: group, text: normalize(group.dataset.categorySearchText),
                children: [...group.querySelectorAll(".category-child")].map(label => ({ element: label, text: normalize(label.dataset.categorySearchText) })),
                openBeforeSearch: group.open,
            }));
            let searching = false;
            const searchCategories = () => {
                const terms = normalize(search?.value).trim().split(/\s+/).filter(Boolean);
                const active = terms.length > 0;
                if (active && !searching) groups.forEach(group => { group.openBeforeSearch = group.element.open; });
                const matches = text => terms.every(term => text.includes(term));
                let visible = 0;
                groups.forEach(group => {
                    const parentMatches = active && matches(group.text);
                    let childrenVisible = 0;
                    group.children.forEach(child => {
                        child.element.hidden = active && !parentMatches && !matches(child.text);
                        if (!child.element.hidden) childrenVisible++;
                    });
                    group.element.hidden = active && !parentMatches && childrenVisible === 0;
                    if (active && !group.element.hidden) group.element.open = true;
                    else if (!active && searching) group.element.open = group.openBeforeSearch;
                    if (!group.element.hidden) visible += childrenVisible + (group.element.querySelector("[data-category-parent]") ? 1 : 0);
                });
                filter.querySelectorAll(".category-tree > .filter-empty").forEach(empty => { empty.hidden = active; });
                if (clearSearch) clearSearch.hidden = !search?.value;
                if (searchStatus) {
                    searchStatus.hidden = !active;
                    searchStatus.textContent = visible ? `${visible} categoria${visible === 1 ? " exibida" : "s exibidas"}.` : "Nenhuma categoria encontrada.";
                }
                searching = active;
            };
            search?.addEventListener("input", searchCategories);
            clearSearch?.addEventListener("click", () => { search.value = ""; searchCategories(); search.focus(); });
            search?.addEventListener("keydown", event => {
                if (event.key === "Enter") event.preventDefault();
                if (event.key === "Escape" && search.value) {
                    event.preventDefault();
                    event.stopPropagation();
                    search.value = "";
                    searchCategories();
                }
            });
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
