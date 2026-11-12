(() => {
    const all = document.querySelector('[data-rep-all]');
    const items = Array.from(document.querySelectorAll('[data-rep-item]'));
    const count = document.querySelector('[data-rep-count]');
    const submit = document.querySelector('[data-rep-submit]');
    const update = () => {
        const selected = items.filter(item => item.checked).length;
        if (count) count.textContent = `${selected} ${selected === 1 ? 'item selecionado' : 'itens selecionados'}`;
        if (submit) submit.disabled = selected === 0;
        if (all) {
            all.checked = selected > 0 && selected === items.length;
            all.indeterminate = selected > 0 && selected < items.length;
            all.disabled = items.length === 0;
        }
    };
    all?.addEventListener('change', () => { items.forEach(item => { item.checked = all.checked; }); update(); });
    items.forEach(item => item.addEventListener('change', update));
    update();

    const matrix = document.getElementById('id_matriz');
    const destinations = document.querySelector('[data-rep-config-destinos]');
    if (matrix && destinations) {
        const choices = Array.from(destinations.querySelectorAll('input[type="checkbox"]'));
        const members = document.querySelector('[data-rep-members]');
        const refresh = () => {
            choices.forEach(choice => {
                const isMatrix = choice.value === matrix.value;
                if (isMatrix) choice.checked = false;
                choice.disabled = isMatrix;
                const row = choice.closest('label')?.parentElement;
                if (row) row.hidden = isMatrix;
            });
            const selected = choices.filter(choice => choice.checked && !choice.disabled);
            if (members) members.textContent = selected.length
                ? `${selected.length} ${selected.length === 1 ? 'empresa FILHO selecionada' : 'empresas FILHO selecionadas'}. A padronização completa será feita em uma por solicitação.`
                : 'Escolha a base PAI e marque ao menos uma empresa FILHO.';
        };
        matrix.addEventListener('change', refresh);
        choices.forEach(choice => choice.addEventListener('change', refresh));
        refresh();
    }

    document.querySelectorAll('[data-concil-grupo]').forEach(group => {
        const fieldset = group.closest('fieldset');
        const refresh = () => {
            fieldset.querySelectorAll(`[data-concil-pai="${group.dataset.concilGrupo}"] select`).forEach(select => {
                const ignored = group.value === 'ignorar';
                select.disabled = ignored;
                if (ignored) { select.value = 'ignorar'; return; }
                const code = group.value.startsWith('usar:') ? group.value.slice(5) : null;
                Array.from(select.options).forEach(option => {
                    if (option.dataset.concilGrupoDestino) option.disabled = option.dataset.concilGrupoDestino !== code;
                });
                if (select.selectedOptions[0]?.disabled) select.value = '';
            });
        };
        group.addEventListener('change', refresh);
        refresh();
    });

    document.querySelectorAll('[data-concil-lote]').forEach(section => {
        const rows = Array.from(section.querySelectorAll('[data-concil-row]'));
        const all = section.querySelector('[data-concil-all]');
        const action = section.querySelector('[data-concil-bulk-action]');
        const apply = section.querySelector('[data-concil-apply]');
        const feedback = section.querySelector('[data-concil-feedback]');
        const eligible = row => !row.querySelector('[data-concil-action]').disabled;
        const selected = () => rows.filter(row => eligible(row) && row.querySelector('[data-concil-check]').checked);
        const refresh = () => {
            rows.forEach(row => {
                const check = row.querySelector('[data-concil-check]');
                check.disabled = !eligible(row);
                if (check.disabled) check.checked = false;
            });
            const available = rows.filter(eligible).length;
            const count = selected().length;
            section.querySelector('[data-concil-count]').textContent = `${count} selecionado(s)`;
            all.checked = count > 0 && count === available;
            all.indeterminate = count > 0 && count < available;
            all.disabled = available === 0;
            apply.disabled = count === 0 || !action.value;
        };
        all.addEventListener('change', () => {
            rows.forEach(row => { row.querySelector('[data-concil-check]').checked = eligible(row) && all.checked; });
            refresh();
        });
        section.addEventListener('change', event => {
            if (event.target.matches('[data-concil-action]')) event.target.closest('[data-concil-row]').querySelector('[data-concil-row-feedback]').textContent = '';
            refresh();
        });
        // Group decisions can disable children in this section.
        section.closest('fieldset').addEventListener('change', refresh);
        section.querySelector('[data-concil-clear]').addEventListener('click', () => {
            rows.forEach(row => { row.querySelector('[data-concil-check]').checked = false; });
            feedback.textContent = ''; refresh();
        });
        apply.addEventListener('click', () => {
            let applied = 0, skipped = 0;
            selected().forEach(row => {
                const select = row.querySelector('[data-concil-action]');
                const note = row.querySelector('[data-concil-row-feedback]');
                note.textContent = '';
                if (select.disabled) { skipped++; return; }
                const options = Array.from(select.options).filter(option => option.value && !option.disabled);
                let matches;
                if (['reaproveitar', 'reativar'].includes(action.value)) {
                    matches = options.filter(option => option.value.startsWith('usar:')
                        && option.dataset.concilCompativel === 'sim'
                        && option.dataset.concilInativa === (action.value === 'reativar' ? 'sim' : 'nao'));
                } else matches = options.filter(option => option.value === action.value);
                // A reused record must stay active, including when selecting retirement in bulk.
                const used = action.value === 'inativar' && Array.from(section.closest('fieldset').querySelectorAll('[data-concil-lote]'))
                    .filter(other => other !== section).some(other => Array.from(other.querySelectorAll('[data-concil-action]'))
                        .some(source => !source.disabled && source.value === `usar:${row.dataset.concilCodigo}`));
                if (matches.length !== 1 || used) {
                    skipped++;
                    note.textContent = used ? 'Categoria reaproveitada: deve permanecer ativa.' : 'Ação indisponível ou ambígua: revise esta linha.';
                    return;
                }
                select.value = matches[0].value;
                select.dispatchEvent(new Event('change', {bubbles: true}));
                applied++;
            });
            feedback.textContent = `${applied} ação(ões) preenchida(s); ${skipped} linha(s) não aplicada(s). Revise as decisões antes de confirmar o envio.`;
            refresh();
        });
        refresh();
    });

    const selection = document.querySelector('[data-rep-selection]');
    document.querySelector('[data-rep-open-selection]')?.addEventListener('click', () => {
        const details = document.getElementById('rep-selecao');
        if (details) { details.open = true; details.scrollIntoView({behavior: 'smooth', block: 'start'}); }
        selection?.querySelector('[data-rep-selection-search]')?.focus({preventScroll: true});
    });
    if (selection) {
        const rows = Array.from(selection.querySelectorAll('[data-rep-source-row]'));
        const check = row => row.querySelector('[data-rep-source-check]');
        const action = selection.querySelector('[name="acao"]');
        const search = selection.querySelector('[data-rep-selection-search]');
        const all = selection.querySelector('[data-rep-selection-all]');
        const destAll = selection.querySelector('[data-rep-dest-all]');
        const destinations = Array.from(selection.querySelectorAll('[name="destinos"]'));
        const submit = selection.querySelector('[data-rep-selection-submit]');
        const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
        const eligible = row => check(row) && !check(row).disabled;
        const visible = () => rows.filter(row => !row.hidden && eligible(row));
        const selectChildren = row => {
            if (row.dataset.grupo !== 'sim') return;
            rows.filter(child => child.dataset.pai === row.dataset.codigo && eligible(child)).forEach(child => {
                const desired = 'nao';
                check(child).checked = check(row).checked && child.dataset.inativa === desired;
            });
        };
        const refresh = () => {
            const selected = rows.filter(row => eligible(row) && check(row).checked);
            const count = action.value === 'replicar' ? selected.length : selected.filter(row => row.dataset.grupo !== 'sim').length;
            selection.querySelector('[data-rep-selection-count]').textContent = `${count} cadastro(s) · ${destinations.filter(c => c.checked).length} destino(s)`;
            const shown = visible(), checked = shown.filter(row => check(row).checked).length;
            all.checked = shown.length > 0 && checked === shown.length;
            all.indeterminate = checked > 0 && checked < shown.length;
            all.disabled = !shown.length;
            const destCount = destinations.filter(c => c.checked).length;
            destAll.checked = destCount > 0 && destCount === destinations.length;
            destAll.indeterminate = destCount > 0 && destCount < destinations.length;
            submit.disabled = submit.dataset.repLocked === 'sim' || count === 0 || destCount === 0;
        };
        rows.forEach(row => check(row)?.addEventListener('change', () => { selectChildren(row); refresh(); }));
        all.addEventListener('change', () => { visible().forEach(row => { check(row).checked = all.checked; }); refresh(); });
        action.addEventListener('change', () => { rows.filter(row => eligible(row) && check(row).checked).forEach(selectChildren); refresh(); });
        search.addEventListener('input', () => {
            const term = normalize(search.value.trim());
            rows.forEach(row => { row.hidden = !normalize(row.dataset.texto).includes(term); });
            refresh();
        });
        destAll.addEventListener('change', () => { destinations.forEach(c => { c.checked = destAll.checked; }); refresh(); });
        destinations.forEach(c => c.addEventListener('change', refresh));
        refresh();
    }

    const panel = document.querySelector('[data-rep-progress]');
    if (!panel) return;
    const labels = {fila: 'Na fila', consultando: 'Verificando OMIEs', revisao: 'Aguardando sua decisão',
        enviando: 'Cadastrando no grupo', concluido: 'Processamento concluído', erro: 'Consulta não concluída',
        pendente: 'Aguardando consulta', pronta: 'Verificada', executando: 'Cadastrando', sucesso: 'Confirmado',
        cancelada: 'Requisição cancelada', bloqueada: 'Bloqueada', ignorada: 'Ignorada', incerto: 'Verificar resultado'};
    if (panel.dataset.repMode === 'inativar') labels.enviando = 'Inativando categorias';
    if (panel.dataset.repMode === 'reativar') labels.enviando = 'Reativando categorias';
    if (panel.dataset.repMode === 'espelho') labels.enviando = 'Padronizando plano';
    if (panel.dataset.repMode === 'conciliacao') labels.enviando = 'Conciliando plano';
    if (panel.dataset.repMode === 'lote') labels.enviando = 'Processando categorias';
    let stopped = false;
    let state = panel.dataset.repState;
    const pollMessage = panel.querySelector('[data-rep-poll-message]');
    const poll = async () => {
        if (stopped) return;
        if (document.hidden) { window.setTimeout(poll, 3000); return; }
        try {
            const response = await fetch(panel.dataset.repProgress, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
            if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
            const data = await response.json();
            panel.dataset.repResult = data.resultado || 'andamento';
            const summary = panel.querySelector('[data-rep-resumo]');
            if (summary && data.resumo) summary.textContent = `${data.resumo.sucesso} confirmadas · ${data.resumo.ignorada} ignoradas · ${data.resumo.pendente} aguardando/pendentes`;
            panel.querySelector('[data-rep-percent]').textContent = `${data.percentual}%`;
            panel.querySelector('[data-rep-bar]').style.width = `${data.percentual}%`;
            panel.querySelector('[role="progressbar"]').setAttribute('aria-valuenow', data.percentual);
            panel.querySelector('[data-rep-message]').textContent = data.mensagem;
            panel.querySelector('[data-rep-status]').textContent = data.status === 'concluido' ? (data.rotulo || labels[data.status]) : (labels[data.status] || data.status);
            panel.querySelector('[data-rep-stages]').textContent = `${data.atual} de ${data.total} etapas concluídas`;
            const errors = panel.querySelector('[data-rep-pendencias]');
            if (errors) {
                const list = errors.querySelector('ul');
                list.replaceChildren();
                (data.pendencias || []).forEach(item => {
                    const row = document.createElement('li');
                    row.className = 'mb-2';
                    const title = document.createElement('strong');
                    title.textContent = [item.empresa, item.categoria, item.codigo && `Código ${item.codigo}`, item.metodo].filter(Boolean).join(' · ');
                    const message = document.createElement('div');
                    message.textContent = item.mensagem || '';
                    row.append(title, message);
                    if (item.detalhe && !(item.mensagem || '').includes(item.detalhe)) {
                        const detail = document.createElement('div');
                        detail.textContent = item.detalhe;
                        row.append(detail);
                    }
                    list.append(row);
                });
                errors.hidden = !list.children.length || data.status === 'revisao';
            }
            data.empresas.forEach(company => {
                const row = document.querySelector(`[data-rep-company="${company.id}"]`);
                if (!row) return;
                row.dataset.status = company.status;
                row.querySelector('[data-rep-company-status]').textContent = company.status === 'revisao' && ['espelho', 'conciliacao', 'inativar', 'reativar', 'lote'].includes(panel.dataset.repMode) ? 'Aguardando confirmação' : labels[company.status] || company.status;
                row.querySelector('[data-rep-company-message]').textContent = company.mensagem;
            });
            pollMessage.textContent = '';
            if (state !== data.status && !data.ativo) { window.location.reload(); return; }
            state = data.status;
            if (!data.ativo) return;
        } catch (_) {
            pollMessage.textContent = 'A atualização automática está indisponível. Tentando novamente; você também pode atualizar os resultados.';
        }
        window.setTimeout(poll, 3000);
    };
    if (['fila', 'consultando', 'enviando'].includes(state)) window.setTimeout(poll, 1000);
    window.addEventListener('pagehide', () => { stopped = true; }, {once: true});
})();
