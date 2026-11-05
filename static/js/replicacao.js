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

    const group = document.querySelector('[data-rep-grupo]');
    const matrix = document.getElementById('id_matriz');
    const groupData = document.getElementById('rep-grupo-empresas');
    if (group && matrix && groupData) {
        const companies = JSON.parse(groupData.textContent);
        const members = document.querySelector('[data-rep-members]');
        const refresh = () => {
            const selected = matrix.value;
            const participants = companies.filter(company => company.grupo.toLocaleLowerCase('pt-BR') === group.value.toLocaleLowerCase('pt-BR'));
            matrix.replaceChildren(new Option('Selecione a base PAI', ''));
            participants.forEach(company => matrix.add(new Option(company.nome, String(company.id))));
            if (participants.some(company => String(company.id) === selected)) matrix.value = selected;
            if (members) members.textContent = participants.length
                ? participants.map(company => company.nome).join(' • ')
                : 'Selecione um grupo com ao menos duas empresas ativas.';
        };
        group.addEventListener('change', refresh);
        refresh();
    }

    const panel = document.querySelector('[data-rep-progress]');
    if (!panel) return;
    const labels = {fila: 'Na fila', consultando: 'Verificando OMIEs', revisao: 'Aguardando sua decisão',
        enviando: 'Cadastrando no grupo', concluido: 'Processamento concluído', erro: 'Consulta não concluída',
        pendente: 'Aguardando consulta', pronta: 'Verificada', executando: 'Cadastrando', sucesso: 'Confirmado',
        ignorada: 'Ignorada', incerto: 'Verificar resultado'};
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
            panel.querySelector('[data-rep-percent]').textContent = `${data.percentual}%`;
            panel.querySelector('[data-rep-bar]').style.width = `${data.percentual}%`;
            panel.querySelector('[role="progressbar"]').setAttribute('aria-valuenow', data.percentual);
            panel.querySelector('[data-rep-message]').textContent = data.mensagem;
            panel.querySelector('[data-rep-status]').textContent = labels[data.status] || data.status;
            panel.querySelector('[data-rep-stages]').textContent = `${data.atual} de ${data.total} etapas concluídas`;
            data.empresas.forEach(company => {
                const row = document.querySelector(`[data-rep-company="${company.id}"]`);
                if (!row) return;
                row.querySelector('[data-rep-company-status]').textContent = labels[company.status] || company.status;
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
