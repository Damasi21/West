REGRAS = {
    "cadastro_incompleto": {
        "titulo": "Cadastro de fornecedor incompleto", "severidade": "atencao",
        "descricao": "Nome ou CPF/CNPJ ausente em fornecedor nacional ativo.",
        "recomendacao": "Conferir o cadastro e solicitar os dados ausentes ao responsavel.",
    },
    "titulo_duplicado": {
        "titulo": "Possivel duplicidade de titulos", "severidade": "alto",
        "descricao": "Mesmo parceiro, documento, parcela, valor original e vencimento. Correspondencia provavel, nao confirmacao de duplicidade.",
        "recomendacao": "Comparar os documentos de origem e verificar parcelas, serie e eventuais relancamentos antes de concluir.",
    },
    "valor_atipico": {
        "titulo": "Valor acima do historico", "severidade": "atencao",
        "descricao": "Valor superior ao multiplicador da mediana e a tres desvios absolutos medianos do parceiro, usando datas anteriores.",
        "recomendacao": "Conferir quantidade, escopo, recorrencia e documentos que justifiquem o valor.",
    },
    "categoria_atipica": {
        "titulo": "Categoria incomum para o parceiro", "severidade": "atencao",
        "descricao": "Categoria nova quando uma categoria representa ao menos 80% do historico anterior do parceiro.",
        "recomendacao": "Verificar a natureza da despesa ou receita e a politica de classificacao da empresa.",
    },
    "alteracao_bancaria": {
        "titulo": "Dados bancarios alterados entre capturas", "severidade": "alto",
        "descricao": "Compara os dados bancarios atuais com a ultima captura do Auditor. A primeira captura estabelece a referencia.",
        "recomendacao": "Confirmar a alteracao por um canal conhecido do fornecedor. Nao ha confirmacao do beneficiario efetivamente pago nesta regra.",
    },
}
PARAMETROS = {"amostras_minimas": 6, "multiplicador_valor": 3, "janela_dias": 365}
VERSAO_REGRAS = "1"
