"""Comparação determinística; nomes/códigos isolados nunca autorizam alterações."""
import re
import unicodedata
import hashlib
import json
from difflib import SequenceMatcher

from .models import ItemReplicacao


def normalizar(valor):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(valor or "")) if not unicodedata.combining(c)).casefold().split())


def _nome_comparavel(valor):
    return " ".join(re.findall(r"[a-z0-9]+", normalizar(valor)))


def _singular_sugerido(palavra):
    # A spelling heuristic for ranking only, never a semantic equivalence rule.
    if len(palavra) < 5:
        return palavra
    for plural, singular in (("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("ois", "ol"), ("uis", "ul"), ("ns", "m")):
        if palavra.endswith(plural):
            return palavra[:-len(plural)] + singular
    return palavra[:-1] if palavra.endswith("s") and not palavra.endswith("ss") else palavra


def semelhanca(a, b):
    a, b = _nome_comparavel(a), _nome_comparavel(b)
    if not a or not b:
        return 0
    if a == b:
        return 1
    # Do not infer matches between short acronyms or different numbered accounts.
    if min(len(a.replace(" ", "")), len(b.replace(" ", ""))) < 5 or set(re.findall(r"\d+", a)) != set(re.findall(r"\d+", b)):
        return 0
    termos_a, termos_b = a.split(), b.split()
    if {_singular_sugerido(p) for p in termos_a} == {_singular_sugerido(p) for p in termos_b}:
        return .97
    indice = min(SequenceMatcher(None, a, b, autojunk=False).ratio(), SequenceMatcher(None, b, a, autojunk=False).ratio())
    return indice if indice >= .8 else 0


def sugestoes_nome(descricao, categorias):
    ordenadas = [(semelhanca(descricao, c.descricao), c) for c in categorias]
    return [c for score, c in sorted(ordenadas, key=lambda par: (-par[0], normalizar(par[1].descricao), par[1].codigo, par[1].pk)) if score >= .8][:5]


def assinatura_semelhantes(origem, candidatos):
    semelhantes = sorted((c for c in candidatos if semelhanca(origem["descricao"], c["descricao"]) >= .8), key=lambda c: c["codigo"])
    return hashlib.sha256(json.dumps(semelhantes, sort_keys=True, ensure_ascii=False).encode()).hexdigest() if semelhantes else ""


def dados(categoria):
    return {campo: getattr(categoria, campo) for campo in (
        "codigo", "descricao", "natureza", "tipo_categoria", "categoria_superior", "totalizadora",
        "conta_inativa", "transferencia", "conta_receita", "conta_despesa", "ativo_omie",
    )}


def tipo(item):
    if str(item["codigo"]).startswith("1") and not item["conta_despesa"]:
        return "R"
    if str(item["codigo"]).startswith("2") and not item["conta_receita"]:
        return "D"
    return ""


def caminho(item, catalogo):
    nomes = [item["descricao"]]
    codigo = item["categoria_superior"]
    visitados = {item["codigo"]}
    while codigo and codigo in catalogo:
        if codigo in visitados or len(visitados) > 10:
            return "Estrutura circular"
        visitados.add(codigo)
        pai = catalogo[codigo]
        nomes.insert(0, pai["descricao"])
        codigo = pai["categoria_superior"]
    if len(nomes) == 1 and not item["totalizadora"]:
        nomes.insert(0, "Receitas" if tipo(item) == "R" else "Despesas")
    return " → ".join(nomes)[:500]


def impedimento(item, catalogo):
    if not item["ativo_omie"] or item["conta_inativa"] or item["transferencia"]:
        return "Categorias inativas ou de transferência não são replicadas nesta etapa."
    if not tipo(item):
        return "Não foi possível identificar o tipo receita/despesa."
    if not item["descricao"].strip() or len(item["descricao"]) > 50 or len(item["natureza"]) > 50:
        return "Descrição e natureza devem respeitar o limite de 50 caracteres da OMIE."
    if caminho(item, catalogo) == "Estrutura circular":
        return "A hierarquia da matriz contém um ciclo."
    if item["totalizadora"] and not re.fullmatch(r"[12]\.\d{2}", item["codigo"]):
        return "Os níveis principais da estrutura OMIE não são criados ou alterados por esta rotina."
    if not item["totalizadora"]:
        pai = catalogo.get(item["categoria_superior"])
        if not pai or not pai["totalizadora"] or not re.fullmatch(r"[12]\.\d{2}", pai["codigo"]):
            return "A categoria precisa estar vinculada a um grupo válido da matriz."
    return ""


def equivalentes(origem, destino):
    campos = ["descricao", "natureza"]
    if not origem["totalizadora"]:
        campos.append("tipo_categoria")
    return all(origem[campo] == destino[campo] for campo in campos)


def compativel(origem, destino, codigo_pai=None):
    if not destino["ativo_omie"] or destino["conta_inativa"] or destino["transferencia"]:
        return False
    if origem["totalizadora"] != destino["totalizadora"] or tipo(origem) != tipo(destino):
        return False
    return origem["totalizadora"] or bool(codigo_pai and destino["categoria_superior"] == codigo_pai)


def gerar_linhas(comparacao, destino, origens, catalogo_destino, vinculos):
    fontes = {c.codigo: dados(c) for c in origens}
    alvos = {c.codigo: dados(c) for c in catalogo_destino}
    por_codigo = {c.codigo: c for c in catalogo_destino}
    vinculados = {v.origem.codigo: v.categoria.codigo for v in vinculos}
    propostos = dict(vinculados)
    linhas = []
    # Groups are resolved first; a selected child requires its parent mapping.
    for categoria in sorted(origens, key=lambda c: (not c.totalizadora, c.codigo)):
        origem = fontes[categoria.codigo]
        item = ItemReplicacao(comparacao=comparacao, destino=destino, origem=categoria,
            matriz_dados=origem, caminho=caminho(origem, fontes), situacao="criar")
        item.mensagem = impedimento(origem, fontes)
        codigo_pai = propostos.get(origem["categoria_superior"])
        possiveis = [c for c in catalogo_destino if compativel(origem, alvos[c.codigo], codigo_pai)]
        item.candidatos = []
        if item.mensagem:
            item.situacao = "bloqueado"
        elif origem["codigo"] in vinculados:
            alvo = por_codigo.get(vinculados[origem["codigo"]])
            if not alvo or alvo not in possiveis:
                item.situacao = "bloqueado"
                item.mensagem = "O vínculo existente mudou de tipo, hierarquia ou disponibilidade. Revise os cadastros na OMIE."
            else:
                item.categoria = alvo
        else:
            iguais = [c for c in possiveis if normalizar(c.descricao) == normalizar(origem["descricao"])]
            repetidas = [o for o in fontes.values() if o["totalizadora"] == origem["totalizadora"] and o["categoria_superior"] == origem["categoria_superior"] and normalizar(o["descricao"]) == normalizar(origem["descricao"])]
            if len(iguais) > 1 or len(repetidas) > 1:
                item.situacao = "ambiguo"
                item.mensagem = "Há nomes repetidos. Escolha explicitamente o cadastro correspondente."
            elif len(iguais) == 1:
                item.categoria = iguais[0]
            elif (sugestoes := sugestoes_nome(origem["descricao"], possiveis)):
                item.candidatos = [c.pk for c in sugestoes]
                item.situacao = "ambiguo"
                item.mensagem = "Há nomes semelhantes no destino. Revise se representam a mesma categoria antes de criar ou padronizar."
            elif origem["codigo"] in por_codigo:
                item.situacao = "ambiguo"
                item.mensagem = "O mesmo código existe com outro significado. Escolha o correspondente ou marque como nova categoria."
            else:
                item.mensagem = "Criar um novo grupo." if origem["totalizadora"] else "Criar após confirmar o vínculo do grupo superior."
        if item.categoria:
            item.destino_dados = alvos[item.categoria.codigo]
            item.situacao = "igual" if equivalentes(origem, item.destino_dados) else "alterar"
            item.mensagem = "Vincular o cadastro correspondente." if item.situacao == "igual" else "Revisar descrição, natureza e tipo de categoria antes de atualizar."
            propostos[origem["codigo"]] = item.categoria.codigo
        linhas.append(item)
    return linhas
