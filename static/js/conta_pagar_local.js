(() => {
    const root = document.querySelector("[data-local-payable]");
    if (!root) return;
    const dialog = root.querySelector("[data-local-dialog]");
    const content = root.querySelector("[data-local-content]");
    const feedback = root.querySelector("[data-local-feedback]");
    const title = root.querySelector("#local-payable-title");
    const supplierDialog = root.querySelector("[data-local-supplier-dialog]");
    const supplierSearch = root.querySelector("[data-local-supplier-search]");
    const supplierResults = root.querySelector("[data-local-supplier-results]");
    const supplierConfirm = root.querySelector("[data-local-supplier-confirm]");
    const supplierCount = root.querySelector("[data-local-supplier-count]");
    const sendDialog = root.querySelector("[data-local-send-dialog]");
    const sendConfirm = root.querySelector("[data-local-send-confirm]");
    const sendFeedback = root.querySelector("[data-local-send-feedback]");
    let sendIds = [];
    let activeMode = "";
    let currentPage = 1;
    let listTimer;
    let supplierSelect = null;
    let supplierOptions = [];
    let selectedSupplier = "";
    let files = [];
    let saving = false;
    let requestNumber = 0;
    const tell = (message, success = false) => {
        feedback.textContent = message;
        feedback.classList.toggle("is-success", success);
    };
    const close = () => { if (!saving) { requestNumber++; clearTimeout(listTimer); if (supplierDialog.open) supplierDialog.close(); if (sendDialog.open) sendDialog.close(); dialog.close(); } };
    const normalizeSearch = value => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const updateSupplierLabel = select => {
        const label = content.querySelector("[data-local-supplier-label]");
        if (label) label.textContent = select.value ? select.selectedOptions[0].textContent : "Selecionar fornecedor";
    };
    const renderSuppliers = () => {
        const query = normalizeSearch(supplierSearch.value);
        const options = supplierOptions.filter(option => normalizeSearch(option.textContent).includes(query));
        if (!options.some(option => option.value === selectedSupplier)) selectedSupplier = "";
        supplierResults.replaceChildren();
        options.forEach(option => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "local-supplier-option";
            button.dataset.localSupplierValue = option.value;
            button.classList.toggle("is-selected", selectedSupplier === option.value);
            button.setAttribute("aria-pressed", String(selectedSupplier === option.value));
            const icon = document.createElement("i");
            icon.className = "bi bi-building";
            icon.setAttribute("aria-hidden", "true");
            const name = document.createElement("strong");
            name.textContent = option.textContent;
            const check = document.createElement("i");
            check.className = "bi bi-check-circle";
            check.setAttribute("aria-hidden", "true");
            button.append(icon, name, check);
            button.addEventListener("click", () => {
                selectedSupplier = option.value;
                supplierResults.querySelectorAll("[data-local-supplier-value]").forEach(item => {
                    const selected = item.dataset.localSupplierValue === selectedSupplier;
                    item.classList.toggle("is-selected", selected);
                    item.setAttribute("aria-pressed", String(selected));
                });
                supplierConfirm.disabled = false;
            });
            supplierResults.append(button);
        });
        if (!options.length) {
            const empty = document.createElement("p");
            empty.className = "local-supplier-empty";
            empty.textContent = supplierOptions.length ? "Nenhum fornecedor encontrado." : "Nenhum fornecedor ativo cadastrado nesta empresa.";
            supplierResults.append(empty);
        }
        supplierCount.textContent = `${options.length} fornecedor${options.length === 1 ? "" : "es"}`;
        supplierConfirm.disabled = !selectedSupplier;
    };
    const openSupplier = select => {
        if (saving) return;
        supplierSelect = select;
        supplierOptions = [...select.options].filter(option => option.value);
        selectedSupplier = select.value;
        supplierSearch.value = "";
        renderSuppliers();
        supplierDialog.showModal();
        supplierResults.scrollTop = 0;
        supplierSearch.focus();
    };
    const size = bytes => bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
    const renderFiles = () => {
        const list = content.querySelector("[data-local-attachments]");
        if (!list) return;
        list.replaceChildren();
        content.querySelector("[data-local-file-count]").textContent = files.length;
        files.forEach((file, index) => {
            const li = document.createElement("li");
            const icon = document.createElement("i");
            icon.className = file.name.toLowerCase().endsWith(".pdf") ? "bi bi-file-earmark-pdf" : "bi bi-file-earmark-image";
            icon.setAttribute("aria-hidden", "true");
            const info = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = file.name;
            const details = document.createElement("small");
            details.textContent = size(file.size);
            info.append(name, details);
            const remove = document.createElement("button");
            remove.type = "button";
            remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
            remove.setAttribute("aria-label", `Remover ${file.name}`);
            remove.title = `Remover ${file.name}`;
            remove.addEventListener("click", () => { files.splice(index, 1); renderFiles(); });
            li.append(icon, info, remove);
            list.append(li);
        });
    };
    const addFiles = incoming => {
        if (saving) return;
        const merged = [...files];
        for (const file of incoming) {
            if (!/\.(pdf|png|jpe?g)$/i.test(file.name) || !file.size || file.size > 10 * 1024 * 1024) {
                tell("Use arquivos PDF, PNG ou JPG com ate 10 MB cada.");
                return;
            }
            if (!merged.some(old => old.name === file.name && old.size === file.size && old.lastModified === file.lastModified)) merged.push(file);
        }
        if (merged.length > 5 || merged.reduce((sum, file) => sum + file.size, 0) > 25 * 1024 * 1024) {
            tell("Anexe no maximo 5 arquivos, com ate 25 MB no total.");
            return;
        }
        files = merged;
        tell("");
        renderFiles();
    };
    const wireForm = () => {
        renderFiles();
        const select = content.querySelector('[name="fornecedor"]');
        if (select) {
            updateSupplierLabel(select);
            content.querySelector("[data-local-supplier-open]").addEventListener("click", () => openSupplier(select));
        }
        content.querySelector("[data-local-files]")?.addEventListener("change", event => { addFiles(event.target.files); event.target.value = ""; });
        content.querySelector("[data-local-clear-files]")?.addEventListener("click", () => { files = []; renderFiles(); });
        const zone = content.querySelector("[data-local-dropzone]");
        zone?.addEventListener("dragover", event => { event.preventDefault(); zone.classList.add("is-dragging"); });
        zone?.addEventListener("dragleave", () => zone.classList.remove("is-dragging"));
        zone?.addEventListener("drop", event => { event.preventDefault(); zone.classList.remove("is-dragging"); addFiles(event.dataTransfer.files); });
        content.querySelector("[data-local-form]")?.addEventListener("submit", save);
    };
    const updateBulk = () => {
        const checks = [...content.querySelectorAll("[data-local-select]")];
        const selected = checks.filter(input => input.checked);
        const all = content.querySelector("[data-local-select-all]");
        if (all) { all.checked = checks.length > 0 && checks.length === selected.length; all.indeterminate = selected.length > 0 && selected.length < checks.length; }
        const button = content.querySelector("[data-local-send-selected]");
        if (button) button.disabled = !selected.length;
    };
    const openSend = ids => {
        if (saving) return;
        sendIds = ids;
        const summary = root.querySelector("[data-local-send-summary]");
        summary.replaceChildren();
        for (const id of ids) {
            const row = content.querySelector(`[data-local-account="${id}"]`);
            if (!row) return;
            const li = document.createElement("li");
            const label = document.createElement("strong");
            label.textContent = row.dataset.localDescription;
            const detail = document.createElement("small");
            detail.textContent = `${row.dataset.localSupplier} / ${row.dataset.localBank}`;
            const amount = document.createElement("b");
            amount.textContent = row.dataset.localAmount;
            li.append(label, detail, amount);
            summary.append(li);
        }
        root.querySelector("[data-local-send-count]").textContent = `${ids.length} conta${ids.length === 1 ? "" : "s"}`;
        sendFeedback.textContent = "";
        sendDialog.showModal();
    };
    const sendAction = async (ids, action) => {
        if (saving) return;
        const csrf = content.querySelector('[name="csrfmiddlewaretoken"]')?.value;
        saving = true;
        sendConfirm.disabled = true;
        tell("");
        sendFeedback.textContent = "";
        try {
            const response = await fetch(root.dataset.sendUrl, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf || "" }, body: JSON.stringify({ ids, acao: action, confirmar: true }) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.mensagem || "Operacao nao autorizada ou indisponivel.");
            saving = false;
            if (sendDialog.open) sendDialog.close();
            await load("list", currentPage);
            tell(data.mensagem, true);
        } catch (error) {
            const message = error.message || "Comunicacao interrompida. Atualize a lista antes de tentar novamente.";
            if (sendDialog.open) sendFeedback.textContent = message;
            else tell(message);
        } finally {
            saving = false;
            sendConfirm.disabled = false;
        }
    };
    const load = async (mode, page = 1, editId = null) => {
        if (saving) return;
        clearTimeout(listTimer);
        activeMode = mode;
        currentPage = page;
        if (supplierDialog.open) supplierDialog.close();
        const number = ++requestNumber;
        files = [];
        tell("");
        title.textContent = mode === "form" ? (editId ? "Editar conta a pagar" : "Nova conta a pagar") : "Cadastros locais";
        content.innerHTML = '<p class="local-payable-loading">Carregando...</p>';
        if (!dialog.open) dialog.showModal();
        try {
            const url = mode === "form" ? root.dataset.formUrl + (editId ? `?conta_id=${editId}` : "") : `${root.dataset.listUrl}?pagina=${page}`;
            const response = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
            if (!response.ok) throw new Error();
            const data = await response.json();
            if (number !== requestNumber || !dialog.open) return;
            content.innerHTML = data.html;
            if (mode === "form") wireForm();
            else {
                updateBulk();
                if (data.pendentes) listTimer = setTimeout(() => {
                    if (dialog.open && activeMode === "list" && !saving && !sendDialog.open && !content.querySelector("[data-local-select]:checked")) load("list", page);
                }, 5000);
            }
            content.scrollTop = 0;
            content.querySelector('input:not([type="hidden"]), select, a, button')?.focus();
        } catch {
            if (number !== requestNumber) return;
            content.replaceChildren();
            tell("Nao foi possivel carregar. Feche e tente novamente; confira tambem sua sessao.");
        }
    };
    async function save(event) {
        event.preventDefault();
        if (saving) return;
        const supplier = event.currentTarget.querySelector('[name="fornecedor"]');
        if (!supplier.value) {
            tell("Selecione um fornecedor antes de salvar.");
            openSupplier(supplier);
            return;
        }
        saving = true;
        tell("");
        const form = event.currentTarget;
        const controls = [...form.querySelectorAll("input, select, textarea, button")];
        const button = form.querySelector("[data-local-save]");
        button.disabled = true;
        button.textContent = "Salvando...";
        try {
            const body = new FormData(form);
            files.forEach(file => body.append("anexos", file));
            controls.forEach(control => { control.disabled = true; });
            const response = await fetch(root.dataset.formUrl, { method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" } });
            const data = await response.json();
            if (!response.ok || !data.sucesso) {
                if (data.html) { content.innerHTML = data.html; wireForm(); }
                tell(response.status === 400 ? "Confira os campos destacados." : "Nao foi possivel salvar. Seus dados foram mantidos para tentar novamente.");
                return;
            }
            root.querySelector("[data-local-count]").textContent = data.quantidade;
            files = [];
            title.textContent = "Conta salva";
            content.innerHTML = '<div class="local-payable-success"><i class="bi bi-check-circle" aria-hidden="true"></i><p></p><div><button type="button" class="btn btn-white" data-local-list-current>Ver cadastros locais</button><button type="button" class="btn btn-primary" data-local-new><i class="bi bi-plus-lg me-2"></i>Nova conta</button></div></div>';
            content.querySelector(".local-payable-success p").textContent = data.mensagem;
            content.scrollTop = 0;
            content.querySelector("button")?.focus();
        } catch {
            tell("Falha ao salvar. Tente novamente; a mesma tentativa nao duplica o cadastro.");
        } finally {
            saving = false;
            controls.forEach(control => { control.disabled = false; });
            const current = content.querySelector("[data-local-save]");
            if (current) { current.disabled = false; current.innerHTML = '<i class="bi bi-save me-2"></i>Salvar conta'; }
        }
    }
    root.querySelector("[data-local-create]").addEventListener("click", () => load("form"));
    root.querySelector("[data-local-list]").addEventListener("click", () => load("list"));
    root.querySelector("[data-local-close]").addEventListener("click", close);
    const closeSend = () => { if (!saving) sendDialog.close(); };
    root.querySelector("[data-local-send-close]").addEventListener("click", closeSend);
    root.querySelector("[data-local-send-cancel]").addEventListener("click", closeSend);
    sendConfirm.addEventListener("click", () => sendAction(sendIds, "enviar"));
    sendDialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
    supplierSearch.addEventListener("input", renderSuppliers);
    supplierDialog.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            supplierDialog.close();
        }
    });
    supplierSearch.addEventListener("keydown", event => {
        if (event.key === "ArrowDown") {
            event.preventDefault();
            supplierResults.querySelector("button")?.focus();
        }
    });
    root.querySelector("[data-local-supplier-close]").addEventListener("click", () => supplierDialog.close());
    root.querySelector("[data-local-supplier-cancel]").addEventListener("click", () => supplierDialog.close());
    supplierConfirm.addEventListener("click", () => {
        if (!selectedSupplier || !supplierSelect?.isConnected || saving) return;
        supplierSelect.value = selectedSupplier;
        supplierSelect.dispatchEvent(new Event("change", { bubbles: true }));
        updateSupplierLabel(supplierSelect);
        content.querySelector("[data-local-supplier-open]").removeAttribute("aria-invalid");
        tell("");
        supplierDialog.close();
    });
    supplierDialog.addEventListener("close", () => { if (dialog.open) content.querySelector("[data-local-supplier-open]")?.focus(); });
    dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); else { requestNumber++; clearTimeout(listTimer); } });
    dialog.addEventListener("dragover", event => event.preventDefault());
    content.addEventListener("click", event => {
        if (event.target.closest("[data-local-cancel]")) close();
        if (event.target.closest("[data-local-new]")) load("form");
        if (event.target.closest("[data-local-list-current]")) load("list");
        const page = event.target.closest("[data-local-page]");
        if (page) load("list", page.dataset.localPage);
        const edit = event.target.closest("[data-local-edit]");
        if (edit) load("form", 1, edit.dataset.localEdit);
        const single = event.target.closest("[data-local-send]");
        if (single) openSend([Number(single.dataset.localSend)]);
        if (event.target.closest("[data-local-send-selected]")) openSend([...content.querySelectorAll("[data-local-select]:checked")].map(input => Number(input.value)));
        const verify = event.target.closest("[data-local-verify]");
        if (verify) sendAction([Number(verify.dataset.localVerify)], "verificar");
    });
    content.addEventListener("change", event => {
        if (event.target.matches("[data-local-select-all]")) content.querySelectorAll("[data-local-select]").forEach(input => { input.checked = event.target.checked; });
        if (event.target.matches("[data-local-select-all], [data-local-select]")) updateBulk();
    });
})();
