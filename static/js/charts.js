window.OesteBI = window.OesteBI || {};

window.OesteBI.criarGrafico = function (elemento, configuracao) {
    if (!elemento || typeof Chart === "undefined") return null;
    return new Chart(elemento, configuracao);
};
