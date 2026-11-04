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
})();
