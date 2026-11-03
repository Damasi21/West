(() => {
    const search = document.querySelector('[data-companies-search]');
    if (!search) return;
    const input = search.querySelector('[data-company-query]');
    const results = search.querySelector('[data-company-results]');
    const empty = document.querySelector('[data-company-empty]');
    const clearButtons = document.querySelectorAll('[data-company-clear]');
    const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
    // Only cards already authorized and rendered by the server are searchable.
    const companies = Array.from(document.querySelectorAll('[data-company-item]'), element => ({
        element,
        name: normalize(element.dataset.companyName),
        cnpj: element.dataset.companyCnpj.replace(/\D/g, ''),
    }));
    const filter = () => {
        const query = normalize(input.value).trim();
        const cnpjQuery = /^[\d\s./-]+$/.test(query) ? query.replace(/\D/g, '') : '';
        const words = query.split(/\s+/).filter(Boolean);
        let count = 0;
        companies.forEach(company => {
            const match = !query || (cnpjQuery ? company.cnpj.includes(cnpjQuery) : words.every(word => company.name.includes(word)));
            company.element.hidden = !match;
            if (match) count++;
        });
        empty.hidden = count !== 0;
        search.querySelector('[data-company-clear]').hidden = !input.value;
        results.textContent = query
            ? `${count} empresa${count === 1 ? '' : 's'} encontrada${count === 1 ? '' : 's'} de ${companies.length} disponíve${companies.length === 1 ? 'l' : 'is'}.`
            : `${companies.length} empresa${companies.length === 1 ? '' : 's'} disponíve${companies.length === 1 ? 'l' : 'is'}.`;
    };
    input.addEventListener('input', filter);
    clearButtons.forEach(button => button.addEventListener('click', () => {
        input.value = '';
        filter();
        input.focus();
    }));
    search.hidden = false;
    filter();
})();
